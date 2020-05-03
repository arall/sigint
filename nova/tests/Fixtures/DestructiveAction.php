<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Support\Collection;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Actions\DestructiveAction as BaseDestructiveAction;
use Laravel\Nova\Fields\ActionFields;

class DestructiveAction extends BaseDestructiveAction
{
    use ProvidesActionFields;

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
}
