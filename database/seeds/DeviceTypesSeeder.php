<?php

use Illuminate\Database\Seeder;
use App\Models\DeviceType;

class DeviceTypesSeeder extends Seeder
{
    /**
     * Run the database seeds.
     *
     * @return void
     */
    public function run()
    {
        DeviceType::firstOrCreate([
            'name' => 'Bluetooth',
        ]);
        DeviceType::firstOrCreate([
            'name' => 'WiFi',
        ]);
        DeviceType::firstOrCreate([
            'name' => 'GSM',
        ]);
    }
}
