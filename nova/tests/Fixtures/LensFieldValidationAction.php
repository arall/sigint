<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Support\Collection;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Fields\ActionFields;
use Laravel\Nova\Fields\Text;

class LensFieldValidationAction extends Action implements ShouldQueue
{
    use InteractsWithQueue;

    /**
     * Perform the action on the given models.
     *
     * @param  \Laravel\Nova\Fields\ActionFields  $fields
     * @param  \Illuminate\Support\Collection  $models
     * @return string|void
     */
    public function handle(ActionFields $fields, Collection $models)
    {
        return Action::message('Worked!');
    }

    /**
     * {@inheritdoc}
     */
    public function fields()
    {
        return [
            Text::make('Reason')->rules('required'),
        ];
    }
}
