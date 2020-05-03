<?php

namespace Laravel\Nova;

use BadMethodCallException;
use Illuminate\Http\Request;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Event;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\Str;
use Laravel\Nova\Actions\ActionResource;
use Laravel\Nova\Events\ServingNova;
use Laravel\Nova\Http\Middleware\RedirectIfAuthenticated;
use Laravel\Nova\Http\Requests\NovaRequest;
use ReflectionClass;
use Symfony\Component\Finder\Finder;

class Nova
{
    use AuthorizesRequests;

    /**
     * The registered dashboard names.
     *
     * @var array
     */
    public static $dashboards = [];

    /**
     * The registered cards for the default dashboard.
     *
     * @var array
     */
    public static $defaultDashboardCards = [];

    /**
     * The registered resource names.
     *
     * @var array
     */
    public static $resources = [];

    /**
     * An index of resource names keyed by the model name.
     *
     * @var array
     */
    public static $resourcesByModel = [];

    /**
     * The callback used to create new users via the CLI.
     *
     * @var \Closure
     */
    public static $createUserCallback;

    /**
     * The callback used to gather new user information via the CLI.
     *
     * @var \Closure
     */
    public static $createUserCommandCallback;

    /**
     * The callable that resolves the user's timezone.
     *
     * @var callable
     */
    public static $userTimezoneCallback;

    /**
     * Indicates if Nova is being used to reset passwords.
     *
     * @var bool
     */
    public static $resetsPasswords = false;

    /**
     * All of the registered Nova tools.
     *
     * @var array
     */
    public static $tools = [];

    /**
     * All of the registered Nova cards.
     *
     * @var array
     */
    public static $cards = [];

    /**
     * All of the registered Nova tool scripts.
     *
     * @var array
     */
    public static $scripts = [];

    /**
     * All of the registered Nova tool CSS.
     *
     * @var array
     */
    public static $styles = [];

    /**
     * The theme CSS files applied to Nova.
     *
     * @var array
     */
    public static $themes = [];

    /**
     * The variables that should be made available on the Nova JavaScript object.
     *
     * @var array
     */
    public static $jsonVariables = [];

    /**
     * The callback used to report Nova's exceptions.
     *
     * @var \Closure
     */
    public static $reportCallback;

    /**
     * Indicates if Nova should register its migrations.
     *
     * @var bool
     */
    public static $runsMigrations = true;

    /**
     * The translations that should be made available on the Nova JavaScript object.
     *
     * @var array
     */
    public static $translations = [];

    /**
     * The callback used to sort Nova resources in the sidebar.
     *
     * @var \Closure
     */
    public static $sortCallback;

    /**
     * Get the current Nova version.
     *
     * @return string
     */
    public static function version()
    {
        return '3.5.0';
    }

    /**
     * Get the app name utilized by Nova.
     *
     * @return string
     */
    public static function name()
    {
        return config('nova.name', 'Nova Site');
    }

    /**
     * Get the URI path prefix utilized by Nova.
     *
     * @return string
     */
    public static function path()
    {
        return config('nova.path', '/nova');
    }

    /**
     * Register the Nova routes.
     *
     * @return \Laravel\Nova\PendingRouteRegistration
     */
    public static function routes()
    {
        Route::aliasMiddleware('nova.guest', RedirectIfAuthenticated::class);

        return new PendingRouteRegistration;
    }

    /**
     * Register an event listener for the Nova "serving" event.
     *
     * @param  \Closure|string  $callback
     * @return void
     */
    public static function serving($callback)
    {
        Event::listen(ServingNova::class, $callback);
    }

    /**
     * Get meta data information about all resources for client side consumption.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function resourceInformation(Request $request)
    {
        return static::resourceCollection()->map(function ($resource) use ($request) {
            return array_merge([
                'uriKey' => $resource::uriKey(),
                'label' => $resource::label(),
                'singularLabel' => $resource::singularLabel(),
                'authorizedToCreate' => $resource::authorizedToCreate($request),
                'searchable' => $resource::searchable(),
                'perPageOptions' => $resource::perPageOptions(),
            ], $resource::additionalInformation($request));
        })->values()->all();
    }

    /**
     * Return the base collection of Nova resources.
     *
     * @return \Laravel\Nova\ResourceCollection
     */
    private static function resourceCollection()
    {
        return ResourceCollection::make(static::$resources);
    }

    /**
     * Return Nova's authorized resources.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Laravel\Nova\ResourceCollection
     */
    public static function authorizedResources(Request $request)
    {
        return static::resourceCollection()->authorized($request);
    }

    /**
     * Get the resources available for the given request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableResources(Request $request)
    {
        return static::authorizedResources($request)
            ->sortBy(static::sortResourcesWith())
            ->all();
    }

    /**
     * Get the resources available for the given request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function globallySearchableResources(Request $request)
    {
        return static::authorizedResources($request)
            ->searchable()
            ->sortBy(static::sortResourcesWith())
            ->all();
    }

    /**
     * Get the resources available for the given request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return Collection
     */
    public static function resourcesForNavigation(Request $request)
    {
        return static::authorizedResources($request)
            ->availableForNavigation($request)
            ->sortBy(static::sortResourcesWith())
            ->all();
    }

    /**
     * Register the given resources.
     *
     * @param  array  $resources
     * @return static
     */
    public static function resources(array $resources)
    {
        static::$resources = array_unique(
            array_merge(static::$resources, $resources)
        );

        return new static;
    }

    /**
     * Replace the registered resources with the given resources.
     *
     * @param  array  $resources
     * @return static
     */
    public static function replaceResources(array $resources)
    {
        static::$resources = $resources;

        return new static;
    }

    /**
     * Get the available resource groups for the given request.
     *
     * @param  Request $request
     * @return array
     */
    public static function groups(Request $request)
    {
        return collect(static::availableResources($request))
                    ->map(function ($item, $key) {
                        return $item::group();
                    })->unique()->values();
    }

    /**
     * Get the grouped resources available for the given request.
     *
     * @param  Request $request
     * @return array
     */
    public static function groupedResources(Request $request)
    {
        return ResourceCollection::make(static::availableResources($request))
            ->grouped()
            ->all();
    }

    /**
     * Get the grouped resources available for the given request.
     *
     * @param  Request  $request
     * @return \Illuminate\Support\Collection
     */
    public static function groupedResourcesForNavigation(Request $request)
    {
        return ResourceCollection::make(static::availableResources($request))
            ->groupedForNavigation($request)
            ->filter->count();
    }

    /**
     * Register all of the resource classes in the given directory.
     *
     * @param  string  $directory
     * @return void
     */
    public static function resourcesIn($directory)
    {
        $namespace = app()->getNamespace();

        $resources = [];

        foreach ((new Finder)->in($directory)->files() as $resource) {
            $resource = $namespace.str_replace(
                ['/', '.php'],
                ['\\', ''],
                Str::after($resource->getPathname(), app_path().DIRECTORY_SEPARATOR)
            );

            if (is_subclass_of($resource, Resource::class) &&
                ! (new ReflectionClass($resource))->isAbstract() &&
                ! (is_subclass_of($resource, ActionResource::class))) {
                $resources[] = $resource;
            }
        }

        static::resources(
            collect($resources)->sort()->all()
        );
    }

    /**
     * Get the resource class name for a given key.
     *
     * @param  string  $key
     * @return string
     */
    public static function resourceForKey($key)
    {
        return static::resourceCollection()->first(function ($value) use ($key) {
            return $value::uriKey() === $key;
        });
    }

    /**
     * Get a new resource instance with the given model instance.
     *
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return \Laravel\Nova\Resource
     */
    public static function newResourceFromModel($model)
    {
        $resource = static::resourceForModel($model);

        return new $resource($model);
    }

    /**
     * Get the resource class name for a given model class.
     *
     * @param  object|string  $class
     * @return string
     */
    public static function resourceForModel($class)
    {
        if (is_object($class)) {
            $class = get_class($class);
        }

        if (isset(static::$resourcesByModel[$class])) {
            return static::$resourcesByModel[$class];
        }

        $resource = static::resourceCollection()->first(function ($value) use ($class) {
            return $value::$model === $class;
        });

        return static::$resourcesByModel[$class] = $resource;
    }

    /**
     * Get a resource instance for a given key.
     *
     * @param  string  $key
     * @return \Laravel\Nova\Resource|null
     */
    public static function resourceInstanceForKey($key)
    {
        if ($resource = static::resourceForKey($key)) {
            return new $resource($resource::newModel());
        }
    }

    /**
     * Get a fresh model instance for the resource with the given key.
     *
     * @param  string  $key
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function modelInstanceForKey($key)
    {
        $resource = static::resourceForKey($key);

        return $resource ? $resource::newModel() : null;
    }

    /**
     * Create a new user instance.
     *
     * @param  \Illuminate\Console\Command
     * @return mixed
     */
    public static function createUser($command)
    {
        if (! static::$createUserCallback) {
            static::createUserUsing();
        }

        return call_user_func(
            static::$createUserCallback,
            ...call_user_func(static::$createUserCommandCallback, $command)
        );
    }

    /**
     * Register the callbacks used to create a new user via the CLI.
     *
     * @param  \Closure  $createUserCommandCallback
     * @param  \Closure  $createUserCallback
     * @return static
     */
    public static function createUserUsing($createUserCommandCallback = null, $createUserCallback = null)
    {
        if (! $createUserCallback) {
            $createUserCallback = $createUserCommandCallback;
            $createUserCommandCallback = null;
        }

        static::$createUserCommandCallback = $createUserCommandCallback ??
                  static::defaultCreateUserCommandCallback();

        static::$createUserCallback = $createUserCallback ??
                  static::defaultCreateUserCallback();

        return new static;
    }

    /**
     * Get the default callback used for the create user command.
     *
     * @return \Closure
     */
    protected static function defaultCreateUserCommandCallback()
    {
        return function ($command) {
            return [
                $command->ask('Name'),
                $command->ask('Email Address'),
                $command->secret('Password'),
            ];
        };
    }

    /**
     * Get the default callback used for creating new Nova users.
     *
     * @return \Closure
     */
    protected static function defaultCreateUserCallback()
    {
        return function ($name, $email, $password) {
            $guard = config('nova.guard') ?: config('auth.defaults.guard');

            $provider = config("auth.guards.{$guard}.provider");

            $model = config("auth.providers.{$provider}.model");

            return tap((new $model)->forceFill([
                'name' => $name,
                'email' => $email,
                'password' => Hash::make($password),
            ]))->save();
        };
    }

    /**
     * Set the callable that resolves the user's preferred timezone.
     *
     * @param  callable  $userTimezoneCallback
     * @return static
     */
    public static function userTimezone($userTimezoneCallback)
    {
        static::$userTimezoneCallback = $userTimezoneCallback;

        return new static;
    }

    /**
     * Resolve the user's preferred timezone.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return string|null
     */
    public static function resolveUserTimezone(Request $request)
    {
        if (static::$userTimezoneCallback) {
            return call_user_func(static::$userTimezoneCallback, $request);
        }
    }

    /**
     * Register new tools with Nova.
     *
     * @param  array  $tools
     * @return static
     */
    public static function tools(array $tools)
    {
        static::$tools = array_merge(
            static::$tools,
            $tools
        );

        return new static;
    }

    /**
     * Get the tools registered with Nova.
     *
     * @return array
     */
    public static function registeredTools()
    {
        return static::$tools;
    }

    /**
     * Boot the available Nova tools.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return void
     */
    public static function bootTools(Request $request)
    {
        collect(static::availableTools($request))->each->boot();
    }

    /**
     * Get the tools registered with Nova.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableTools(Request $request)
    {
        return collect(static::$tools)->filter->authorize($request)->all();
    }

    /**
     * Register new dashboard cards with Nova.
     *
     * @param  array  $cards
     * @return static
     */
    public static function cards(array $cards)
    {
        static::$cards = array_merge(
            static::$cards,
            $cards
        );

        return new static;
    }

    /**
     * Get the cards registered with Nova.
     *
     * @return array
     */
    public static function registeredCards()
    {
        return static::$cards;
    }

    /**
     * Get the cards registered with Nova.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableCards(Request $request)
    {
        return collect(static::$cards)->filter->authorize($request)->all();
    }

    /**
     * Copy the cards to cards to the default dashboard.
     *
     * @return static
     */
    public static function copyDefaultDashboardCards()
    {
        static::$defaultDashboardCards = static::$cards;

        return new static;
    }

    /**
     * Get the dashboards registered with Nova.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableDashboards(Request $request)
    {
        return collect(static::$dashboards)->filter->authorize($request)->all();
    }

    /**
     * Register the dashboards.
     *
     * @param  array  $dashboards
     * @return static
     */
    public static function dashboards(array $dashboards)
    {
        static::$dashboards = array_merge(static::$dashboards, $dashboards);

        return new static;
    }

    /**
     * Get the available dashboard cards for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return Collection
     */
    public static function allAvailableDashboardCards(NovaRequest $request)
    {
        return collect(static::$dashboards)
            ->filter
            ->authorize($request)
            ->flatMap(function ($dashboard) {
                return $dashboard->cards();
            })->merge(static::$cards)
            ->unique()
            ->filter
            ->authorize($request)
            ->values();
    }

    /**
     * Get the available dashboard cards for the given request.
     *
     * @param  string  $dashboard
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return Collection
     */
    public static function availableDashboardCardsForDashboard($dashboard, NovaRequest $request)
    {
        return collect(static::$dashboards)->filter->authorize($request)->filter(function ($dash) use ($dashboard) {
            return $dash->uriKey() === $dashboard;
        })->flatMap(function ($dashboard) {
            return $dashboard->cards();
        })->filter->authorize($request)->values();
    }

    /**
     * Get all of the additional scripts that should be registered.
     *
     * @return array
     */
    public static function allScripts()
    {
        return static::$scripts;
    }

    /**
     * Get all of the available scripts that should be registered.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableScripts(Request $request)
    {
        return static::$scripts;
    }

    /**
     * Get all of the additional stylesheets that should be registered.
     *
     * @return array
     */
    public static function allStyles()
    {
        return static::$styles;
    }

    /**
     * Get all of the available stylesheets that should be registered.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function availableStyles(Request $request)
    {
        return static::$styles;
    }

    /**
     * Get all of the theme stylesheets that should be registered.
     *
     * @return array
     */
    public static function themeStyles()
    {
        return static::$themes;
    }

    /**
     * Register the given script file with Nova.
     *
     * @param  string  $name
     * @param  string  $path
     * @return static
     */
    public static function script($name, $path)
    {
        static::$scripts[$name] = $path;

        return new static;
    }

    /**
     * Register the given remote script file with Nova.
     *
     * @param  string  $path
     * @return static
     */
    public static function remoteScript($path)
    {
        static::$scripts[md5($path)] = $path;

        return new static;
    }

    /**
     * Register the given CSS file with Nova.
     *
     * @param  string  $name
     * @param  string  $path
     * @return static
     */
    public static function style($name, $path)
    {
        static::$styles[$name] = $path;

        return new static;
    }

    /**
     * Register the given theme CSS file with Nova.
     *
     * @param string $publicPath
     * @return static
     */
    public static function theme($publicPath)
    {
        static::$themes[] = $publicPath;
    }

    /**
     * Register the given translations with Nova.
     *
     * @param  array|string  $translations
     * @return static
     */
    public static function translations($translations)
    {
        if (is_string($translations)) {
            if (! is_readable($translations)) {
                return new static;
            }

            $translations = json_decode(file_get_contents($translations), true);
        }

        static::$translations = array_merge(static::$translations, $translations);

        return new static;
    }

    /**
     * Get all of the additional translations that should be loaded.
     *
     * @return array
     */
    public static function allTranslations()
    {
        return static::$translations;
    }

    /**
     * Get the JSON variables that should be provided to the global Nova JavaScript object.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public static function jsonVariables(Request $request)
    {
        return collect(static::$jsonVariables)->map(function ($variable) use ($request) {
            return is_callable($variable) ? $variable($request) : $variable;
        })->all();
    }

    /**
     * Provide additional variables to the global Nova JavaScript object.
     *
     * @param  array  $variables
     * @return static
     */
    public static function provideToScript(array $variables)
    {
        if (empty(static::$jsonVariables)) {
            static::$jsonVariables = [
                'base' => static::path(),
                'userId' => Auth::id() ?? null,
            ];
        }

        static::$jsonVariables = array_merge(static::$jsonVariables, $variables);

        return new static;
    }

    /**
     * Configure Nova to not register its migrations.
     *
     * @return static
     */
    public static function ignoreMigrations()
    {
        static::$runsMigrations = false;

        return new static;
    }

    /**
     * Humanize the given value into a proper name.
     *
     * @param  string  $value
     * @return string
     */
    public static function humanize($value)
    {
        if (is_object($value)) {
            return static::humanize(class_basename(get_class($value)));
        }

        return Str::title(Str::snake($value, ' '));
    }

    /**
     * Register the callback used to set a custom Nova error reporter.
     *
     * @var \Closure
     *
     * @param \Closure $callback
     * @return static
     */
    public static function report($callback)
    {
        static::$reportCallback = $callback;

        return new static;
    }

    /**
     * Enable theming-friendly CSS classes for Nova's built-in Vue components.
     *
     * @return static
     */
    public static function enableThemingClasses()
    {
        static::provideToScript(['themingClasses' => true]);

        return new static;
    }

    /**
     * Dynamically proxy static method calls.
     *
     * @param  string  $method
     * @param  array  $parameters
     * @return void
     */
    public static function __callStatic($method, $parameters)
    {
        if (! property_exists(get_called_class(), $method)) {
            throw new BadMethodCallException("Method {$method} does not exist.");
        }

        return static::${$method};
    }

    /**
     * Return the configured ActionResource class.
     *
     * @return \Laravel\Nova\Actions\ActionResource
     */
    public static function actionResource()
    {
        return config('nova.actions.resource');
    }

    /**
     * Return a new instance of the configured ActionEvent.
     *
     * @return \Laravel\Nova\Actions\ActionEvent
     */
    public static function actionEvent()
    {
        return static::actionResource()::newModel();
    }

    /**
     * Register the callback used to sort Nova resources in the sidebar.
     *
     * @var \Closure
     *
     * @param \Closure $callback
     * @return static
     */
    public static function sortResourcesBy($callback)
    {
        static::$sortCallback = $callback;

        return new static;
    }

    /**
     * Get the sorting strategy to use for Nova resources.
     *
     * @return array
     */
    public static function sortResourcesWith()
    {
        return static::$sortCallback ?? function ($resource) {
            return $resource::label();
        };
    }
}
