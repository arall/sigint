<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Address extends Model
{
    /**
     * The attributes that are guarded.
     *
     * @var array
     */
    protected $guarded = [];

    /**
     * Get the user that the address belongs to.
     */
    public function user()
    {
        return $this->belongsTo(User::class, 'user_id');
    }
}
