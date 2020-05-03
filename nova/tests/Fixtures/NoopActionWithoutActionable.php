<?php

namespace Laravel\Nova\Tests\Fixtures;

use Closure;
use Illuminate\Support\Collection;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Fields\ActionFields;

class NoopActionWithoutActionable extends Action
{
    public $withoutActionEvents = true;

    /**
     * Perform the action on the given models.
     *
     * @param  \Laravel\Nova\Fields\ActionFields  $fields
     * @param  \Illuminate\Support\Collection  $models
     * @return string|void
     */
    public function handle(ActionFields $fields, Collection $models)
    {
        return Action::message('Hello World');
    }

    public function canSee(Closure $callback)
    {
        return false;
    }
}
