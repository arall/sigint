<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Wheel extends Model
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
    public function vehicle()
    {
        return $this->belongsTo(Vehicle::class);
    }

    /**
     * The attribute being tested against.
     *
     * @return string
     */
    public function getTestAttribute()
    {
        return $this->vehicle->id;
    }
}
