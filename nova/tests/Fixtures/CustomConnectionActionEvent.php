<?php

namespace Laravel\Nova\Tests\Fixtures;

use Laravel\Nova\Actions\ActionEvent;

class CustomConnectionActionEvent extends ActionEvent
{
    protected $connection = 'sqlite-custom';
}
