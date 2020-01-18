<?php

use Illuminate\Database\Seeder;
use App\Models\User;

class UsersSeeder extends Seeder
{
    /**
     * Run the database seeds.
     *
     * @return void
     */
    public function run()
    {
        $user = User::firstOrNew([
            'email' => 'admin@sigint.local',
        ]);
        $user->name = 'Admin';
        $user->password = bcrypt('123123');
        $user->save();
    }
}
