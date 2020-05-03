<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\BelongsTo;
use Laravel\Nova\Fields\BelongsToMany;
use Laravel\Nova\Fields\File;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Resource;

class RoleResource extends Resource
{
    /**
     * The model the resource corresponds to.
     *
     * @var string
     */
    public static $model = \Laravel\Nova\Tests\Fixtures\Role::class;

    /**
     * The columns that should be searched.
     *
     * @var array
     */
    public static $search = [
        'id', 'name',
    ];

    /**
     * Determine if the resource should be displayed for the given request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return bool
     */
    public static function authorizedToViewAny(Request $request)
    {
        return $_SERVER['nova.authorize.roles'] ?? true;
    }

    /**
     * Get the fields displayed by the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function fields(Request $request)
    {
        return [
            ID::make('ID', 'id'),

            BelongsTo::make('Created By', 'createdBy', UserResource::class),

            BelongsToMany::make('Users', 'users', UserResource::class)
                ->actions(function ($request) {
                    return [
                        new FailingPivotAction,
                        new NoopAction,
                        new NoopActionWithPivotHandle,
                        new QueuedAction,
                        new QueuedUpdateStatusAction,
                        new UpdateStatusAction,
                    ];
                })
                ->prunable($_SERVER['__nova.role.prunable'] ?? false)
                ->fields(function () {
                    return [
                        $this->when($_SERVER['__nova.role.pivotFile'] ?? false, function () {
                            return File::make('Photo', 'photo');
                        }),

                        tap(Text::make('Admin', 'admin')->rules('required'), function ($field) {
                            if ($_SERVER['nova.roles.hidingAdminPivotField'] ?? false) {
                                $field->onlyOnForms();
                            }
                        }),

                        Text::make('Restricted', 'restricted')->canSee(function () {
                            return false;
                        }),
                    ];
                }),

            Text::make('Name', 'name')->rules('required', 'string', 'max:255'),
        ];
    }

    /**
     * Get the actions displayed by the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function actions(Request $request)
    {
        return [
            new NoopAction,
        ];
    }

    /**
     * Get the filters available for the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function filters(Request $request)
    {
        return [new IdFilter];
    }

    /**
     * Build a "relatable" query for the given resource.
     *
     * This query determines which instances of the model may be attached to other resources.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public static function relatableQuery(NovaRequest $request, $query)
    {
        return $query->where('id', '<', 3);
    }

    /**
     * Get the URI key for the resource.
     *
     * @return string
     */
    public static function uriKey()
    {
        return 'roles';
    }
}
