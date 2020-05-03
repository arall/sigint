<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Recipient extends Model
{
    public function user()
    {
        return $this->belongsTo(User::class, 'email', 'email');
    }
}
