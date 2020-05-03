<?php

namespace Laravel\Nova\Tests\Fixtures;

use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\NovaRequest;

class UserWithCustomFields extends UserResource
{
    public function fieldsForIndex(NovaRequest $request)
    {
        return [
            Text::make('Index Name', 'name'),
        ];
    }

    public function fieldsForDetail(NovaRequest $request)
    {
        return [
            Text::make('Detail Name', 'name'),
        ];
    }

    public function fieldsForUpdate(NovaRequest $request)
    {
        return [
            Text::make('Update Name', 'name'),
        ];
    }

    public function fieldsForCreate(NovaRequest $request)
    {
        return [
            Text::make('Create Name', 'name'),
            Text::make('Nickname', 'nickname'),
        ];
    }
}
