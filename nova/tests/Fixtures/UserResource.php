<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\BelongsToMany;
use Laravel\Nova\Fields\File;
use Laravel\Nova\Fields\HasMany;
use Laravel\Nova\Fields\HasOne;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Fields\KeyValue;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Panel;
use Laravel\Nova\Resource;
use Laravel\Nova\ResourceToolElement;

class UserResource extends Resource
{
    /**
     * The model the resource corresponds to.
     *
     * @var string
     */
    public static $model = \Laravel\Nova\Tests\Fixtures\User::class; /**
     * The columns that should be searched.
     *
     * @var array
     */
    public static $search = [
        'id', 'name', 'email',
    ];

    /**
     * Determine if the given resource is authorizable.
     *
     * @return bool
     */
    public static function authorizable()
    {
        return $_SERVER['nova.user.authorizable'] ?? false;
    }

    /**
     * Determine if the user can add / associate models of the given type to the resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model|string  $model
     * @return bool
     */
    public function authorizedToAdd(NovaRequest $request, $model)
    {
        return $_SERVER['nova.user.relatable'] ?? parent::authorizedToAdd($request, $model);
    }

    /**
     * Indicates whether Nova should check for modifications between viewing and updating a resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return  bool
     */
    public static function trafficCop(Request $request)
    {
        return $_SERVER['nova.user.trafficCop'] ?? static::$trafficCop;
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
            new Panel('Primary', [
                ID::make(),

                Text::make('Name')
                            ->creationRules('required', 'string', 'max:255')
                            ->updateRules('required', 'string', 'max:255')
                            ->rules(function () {
                                return ($_SERVER['nova.user.fixedValuesOnUpdate'] ?? false) && $this->resource->email === 'taylor@laravel.com'
                                    ? ['in:Taylor Otwell'] : [];
                            }),
            ]),

            Text::make('Email')
                ->rules('required', 'email', 'max:254')
                ->creationRules('unique:users,email')
                ->updateRules('unique:users,email,{{resourceId}}'),

            Text::make('Weight')
                ->rules('required')
                ->readonly($_SERVER['weight-field.readonly'] ?? true)
                ->canSee(function () {
                    return $_SERVER['weight-field.canSee'] ?? true;
                }),

            Text::make('Password')
                ->onlyOnForms()
                ->rules('required', 'string', 'min:8')
                ->updateRules(function () {
                    return ($_SERVER['nova.user.fixedValuesOnUpdate'] ?? false) && $this->resource->email === 'taylor@laravel.com'
                        ? ['in:taylorotwell'] : [];
                }),

            Text::make('Restricted')->canSee(function () {
                return false;
            }),

            HasOne::make('Address', 'address', AddressResource::class),
            HasOne::make('Profile', 'profile', ProfileResource::class)->nullable(),
            HasMany::make('Posts', 'posts', PostResource::class),

            $this->rolesFields(),

            BelongsToMany::make('Related Users', 'relatedUsers', self::class),

            Text::make('Index')->onlyOnIndex(),
            Text::make('Detail')->onlyOnDetail(),
            Text::make('Form')->onlyOnForms(),
            Text::make('Update')->onlyOnForms()->hideWhenCreating(),

            Text::make('Computed', function () {
                return 'Computed';
            }),

            Text::make('InvokableComputed', new class {
                public function __invoke()
                {
                    return 'Computed';
                }
            }),

            $this->when(false, function () {
                return Text::make('Test', 'test');
            }),

            $this->when($_SESSION['nova.user.cover'] ?? false, function () {
                return GitHubAvatar::make('Avatar', 'email');
            }),

            new ResourceToolElement('component-name'),
            new MyResourceTool(),

            KeyValue::make('Meta'),
        ];
    }

    public function rolesFields()
    {
        if ($_SERVER['nova.useRolesCustomAttribute'] ?? false) {
            return BelongsToMany::make('Roles', 'userRoles', RoleResource::class)->rules('required');
        }

        return BelongsToMany::make('Roles', 'roles', RoleResource::class)->referToPivotAs($_SERVER['nova.user.rolePivotName'] ?? null)->fields(function () {
            return [
                tap(Text::make('Admin', 'admin')->rules('required'), function ($field) {
                    if ($_SERVER['nova.roles.hidingAdminPivotField'] ?? false) {
                        $field->onlyOnForms();
                    }

                    if ($_SERVER['nova.roles.hideAdminWhenCreating'] ?? false) {
                        $field->hideWhenCreating();
                    }
                }),

                Text::make('Admin', 'pivot-update')->rules('required')->onlyOnForms()->hideWhenCreating(),

                $this->when($_SERVER['__nova.user.pivotFile'] ?? false, function () {
                    return File::make('Photo', 'photo');
                }),

                Text::make('Restricted', 'restricted')->canSee(function () {
                    return false;
                }),
            ];
        });
    }

    /**
     * Return the email field for the resource.
     *
     * @return \Laravel\Nova\Fields\Text
     */
    public function emailField()
    {
        return Text::make('Email')
            ->rules('required', 'email', 'max:254')
            ->creationRules(function ($request) {
                return ['unique:users,email'];
            })
            ->updateRules('unique:users,email,{{resourceId}}')
            ->canSee(function () {
                return $_SERVER['email-field.canSee'] ?? true;
            });
    }

    /**
     * Get the lenses available on the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function lenses(Request $request)
    {
        return [
            new UserLens,
            new GroupingUserLens,
            new PaginatingUserLens,
        ];
    }

    /**
     * Get the actions available for the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function actions(Request $request)
    {
        return [
            new OpensInNewTabAction,
            new RedirectAction,
            new DestructiveAction,
            new EmptyAction,
            new ExceptionAction,
            new FailingAction,
            new NoopAction,
            tap(new QueuedAction, function (QueuedAction $action) {
                if ($_SERVER['nova.user.actionCallbacks'] ?? false) {
                    $action->canRun(function ($request, $model) {
                        return $model->id % 2;
                    });
                    $action->canSee(function () {
                        return true;
                    });
                }
            }),
            new QueuedResourceAction,
            new QueuedUpdateStatusAction,
            new RequiredFieldAction,
            (new UnauthorizedAction)->canSee(function ($request) {
                return false;
            }),
            (new UnrunnableAction)->canSee(function ($request) {
                return true;
            })->canRun(function ($request, $model) {
                return false;
            }),
            (new UnrunnableDestructiveAction)->canRun(function ($request, $model) {
                return false;
            }),
            new UpdateStatusAction,
            new NoopActionWithoutActionable,
            new HandleResultAction,
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
        return [
            (new IdFilter)->canSee(function ($request) {
                return $_SERVER['nova.idFilter.canSee'] ?? true;
            }),

            (new CustomKeyFilter)->canSee(function ($request) {
                return $_SERVER['nova.customKeyFilter.canSee'] ?? true;
            }),

            (new ColumnFilter('id'))->canSee(function ($request) {
                return $_SERVER['nova.columnFilter.canSee'] ?? true;
            }),

            (new CreateDateFilter)->firstDayOfWeek(4)->canSee(function ($request) {
                return $_SERVER['nova.dateFilter.canSee'] ?? true;
            }),
        ];
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
     * Build a "relatable" query for the given resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public static function relatableRoles(NovaRequest $request, $query)
    {
        if (! isset($_SERVER['nova.user.useCustomRelatableRoles'])) {
            return RoleResource::relatableQuery($request, $query);
        }

        $_SERVER['nova.user.relatableRoles'] = $query;

        return $query->where('id', '<', 3);
    }

    /**
     * Get the cards available for the request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function cards(Request $request)
    {
        return [
            (new TotalUsers)->canSee(function ($request) {
                return $_SERVER['nova.totalUsers.canSee'] ?? true;
            }),

            new UserGrowth,
            (new CustomerRevenue)->onlyOnDetail(),
        ];
    }

    /**
     * Get the URI key for the resource.
     *
     * @return string
     */
    public static function uriKey()
    {
        return 'users';
    }
}
