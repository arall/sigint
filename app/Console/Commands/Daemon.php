<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;

class Daemon extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'daemon {wifi_interface?}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Run all the scanners';

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
        $interface = $this->argument('wifi_interface');

        do {
            \Artisan::call('scan:wifi ' . $interface);
            \Artisan::call('scan:bluetooth');
            # sleep(60 * 15);
        } while (true);
    }
}
