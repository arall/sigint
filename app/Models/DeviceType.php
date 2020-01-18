<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class DeviceType extends Model
{
    /**
     * Indicates if the model should be timestamped.
     *
     * @var bool
     */
    public $timestamps = false;

    /**
     * Devices relation.
     */
    public function devices()
    {
        return $this->hasMany('App\Models\Device', 'type_id');
    }
}
