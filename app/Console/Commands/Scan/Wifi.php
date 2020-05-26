<?php

namespace App\Console\Commands\Scan;

use Illuminate\Console\Command;
use App\Models\DeviceType;
use Carbon\Carbon;
use Symfony\Component\Process\Process;

class Wifi extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'scan:wifi {interface?}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Scan for WiFi probes';

    /**
     * Create a new command instance.
     *
     * @return void
     */
    public function __construct()
    {
        parent::__construct();
    }

    /**
     * Execute the console command.
     *
     * @return mixed
     */
    public function handle()
    {
        $interface = $this->argument('interface');

        /*$process = new Process(['timeout', '120s', 'python', 'scripts/wifi.py', $interface]);
        $process->setTimeout(0);
        $process->run();
        $output = $process->getOutput();*/
        $output = shell_exec('timeout 120s scripts/wifi_hop.py ' . $interface);

        //$output = file_get_contents('scripts/outputs/wifi.log');

        $type = DeviceType::whereName('WiFi')->first();

        foreach (preg_split("/((\r?\n)|(\r\n?))/", $output) as $line) {
            if (!isset($line[0]) || $line[0] != "{") {
                continue;
            }

            $line = str_replace("'", '"', $line);
            $line = json_decode($line);

            print_r($line);

            if (!isset($line->mac)) {
                continue;
            }

            $device = $type->devices()->firstOrCreate(['identifier' => $line->mac]);

            $log = $device->logs()->firstOrCreate([
                'timestamp' => new Carbon($line->time),
            ]);

            $log->signal = $line->signal;
            $log->save();

            $device->probes()->firstOrCreate(['ssid' => $line->ssid]);
        }
    }
}
