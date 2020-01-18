<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Vendor extends Model
{
    /**
     * The attributes that are mass assignable.
     *
     * @var array
     */
    protected $fillable = [
        'name',
    ];

    /**
     * Indicates if the model should be timestamped.
     *
     * @var bool
     */
    public $timestamps = false;

    /**
     * Devices relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\hasMany
     */
    public function devices()
    {
        return $this->hasMany('App\Models\Device');
    }

    /**
     * Macs relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\hasMany
     */
    public function macs()
    {
        return $this->hasMany('App\Models\VendorMac');
    }
}
