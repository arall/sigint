<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\BelongsToMany;
use Laravel\Nova\Fields\HasMany;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Panel;
use Laravel\Nova\Resource;

class PanelResource extends Resource
{
    /**
     * The model the resource corresponds to.
     *
     * @var string
     */
    public static $model = \Laravel\Nova\Tests\Fixtures\User::class;

    /**
     * Get the fields displayed by the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function fields(Request $request)
    {
        return [
            new Panel('Basics', [
                ID::make('ID', 'id'),

                Text::make('Name', 'name')
                            ->creationRules('required', 'string', 'max:255')
                            ->updateRules('required', 'string', 'max:255'),

                $this->when(false, function () {
                    return Text::make('Exclude', 'exclude');
                }),
            ]),

            Text::make('Email', 'email'),
            Text::make('Password', 'password'),

            HasMany::make('Posts', 'posts', PostResource::class),
            BelongsToMany::make('Roles', 'roles', RoleResource::class),

            new Panel('Extra', [
                $this->when(true, function () {
                    return Text::make('Include', 'include');
                }),
            ]),
        ];
    }

    /**
     * Get the URI key for the resource.
     *
     * @return string
     */
    public static function uriKey()
    {
        return 'panels';
    }
}
