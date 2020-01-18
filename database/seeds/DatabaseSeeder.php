<?php

use Illuminate\Database\Seeder;

class DatabaseSeeder extends Seeder
{
    /**
     * Seed the application's database.
     *
     * @return void
     */
    public function run()
    {
        $this->call(VendorsSeeder::class);
        $this->call(DeviceTypesSeeder::class);
        $this->call(UsersSeeder::class);
    }
}
