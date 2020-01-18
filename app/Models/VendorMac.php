<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class VendorMac extends Model
{
    /**
     * The attributes that are mass assignable.
     *
     * @var array
     */
    protected $fillable = [
        'mac',
    ];

    /**
     * Indicates if the model should be timestamped.
     *
     * @var bool
     */
    public $timestamps = false;

    /**
     * Vendor relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\hasMany
     */
    public function vendor()
    {
        return $this->hasMany('App\Models\Vendor');
    }
}
