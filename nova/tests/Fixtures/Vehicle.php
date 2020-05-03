<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Vehicle extends Model
{
    /**
     * The attributes that are guarded.
     *
     * @var array
     */
    protected $guarded = [];

    /**
     * Get the wheels that belong to this vehicle.
     */
    public function wheels()
    {
        return $this->hasMany(Wheel::class);
    }
}
