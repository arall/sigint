<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Support\Collection;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Fields\ActionFields;
use Laravel\Nova\Fields\Text;

class QueuedResourceAction extends Action implements ShouldQueue
{
    /**
     * Perform the action on the given models.
     *
     * @param  \Laravel\Nova\Fields\ActionFields  $fields
     * @param  \Illuminate\Support\Collection  $models
     * @return void
     */
    public function handleForUsers(ActionFields $fields, Collection $models)
    {
        $_SERVER['queuedResourceAction.applied'][] = $models;
        $_SERVER['queuedResourceAction.appliedFields'][] = $fields;
    }

    /**
     * Get the fields available on the action.
     *
     * @return array
     */
    public function fields()
    {
        return [
            Text::make('Test', 'test'),
        ];
    }
}
