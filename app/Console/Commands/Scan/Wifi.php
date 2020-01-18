<?php

namespace App\Console\Commands\Scan;

use Illuminate\Console\Command;
use App\Models\DeviceType;
use Carbon\Carbon;

class Wifi extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'scan:wifi';

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
        $output = shell_exec('timeout 60s python scripts/wifi.py');
        // $output = file_get_contents('scripts/outputs/wifi.log');

        $type = DeviceType::whereName('WiFi')->first();

        foreach (preg_split("/((\r?\n)|(\r\n?))/", $output) as $line) {
            if ($line[0] != "{") {
                continue;
            }

            $line = str_replace("'", '"', $line);
            $line = json_decode($line);

            print_r($line);

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
