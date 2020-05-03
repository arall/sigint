<?php

namespace App\Console\Commands\Scan;

use Illuminate\Console\Command;
use App\Models\DeviceType;
use Carbon\Carbon;

class Bluetooth extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'scan:bluetooth';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Scan for Bluetooth devices';

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
        $output = shell_exec('python scripts/bluetooth.py');
        // $output = file_get_contents('scripts/outputs/bluetooth.log');

        $type = DeviceType::whereName('Bluetooth')->first();

        foreach (preg_split("/((\r?\n)|(\r\n?))/", $output) as $line) {
            $line = str_replace("'", '"', $line);
            $line = json_decode($line);

            print_r($line);

            if (!isset($line->mac)) {
                continue;
            }

            $device = $type->devices()->firstOrCreate(['identifier' => $line->mac]);

            if (isset($line->name)) {
                $device->name = $line->name;
                $device->save();
            }

            $log = $device->logs()->firstOrCreate([
                'timestamp' => new Carbon($line->time),
            ]);

            if (isset($line->rssi)) {
                $log->signal = $line->rssi;
                $log->save();
            }
        }
    }
}
