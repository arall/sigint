<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class CustomKey extends Model
{
    protected $primaryKey = 'pk';
}
