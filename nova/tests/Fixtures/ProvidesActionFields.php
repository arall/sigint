<?php

namespace Laravel\Nova\Tests\Fixtures;

use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\NovaRequest;

trait ProvidesActionFields
{
    /**
     * Get the fields available on the action.
     *
     * @return array
     */
    public function fields()
    {
        return [
            Text::make('Test', 'test'),

            new class('Callback', 'callback') extends Text {
                public function fill(NovaRequest $request, $model)
                {
                    return function () {
                        return 'callback';
                    };
                }
            },
        ];
    }
}
