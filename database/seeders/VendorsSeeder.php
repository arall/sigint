<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;
use App\Models\Vendor;

class VendorsSeeder extends Seeder
{
    /**
     * Run the database seeds.
     *
     * @return void
     */
    public function run()
    {
        $content = file_get_contents('database/data/macaddress.io-db.json');

        foreach (preg_split("/((\r?\n)|(\r\n?))/", $content) as $line) {
            $line = json_decode($line);
            if (isset($line->companyName)) {
                $vendor = Vendor::firstOrCreate(['name' => $line->companyName]);
                $vendor->macs()->firstOrCreate(['mac' => $line->oui]);
            }
        }
    }
}
