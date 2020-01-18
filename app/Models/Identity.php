<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Identity extends Model
{
    /**
     * Devices relation.
     */
    public function devices()
    {
        return $this->hasMany('App\Models\Device');
    }
}
