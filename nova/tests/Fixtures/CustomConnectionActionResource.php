<?php

namespace Laravel\Nova\Tests\Fixtures;

use Laravel\Nova\Actions\ActionResource;

class CustomConnectionActionResource extends ActionResource
{
    public static $model = CustomConnectionActionEvent::class;
}
