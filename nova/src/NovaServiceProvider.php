<?php

namespace Laravel\Nova;

use Illuminate\Support\Arr;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\ServiceProvider;
use Laravel\Nova\Events\ServingNova;
use Laravel\Nova\Tools\Dashboard;
use Laravel\Nova\Tools\ResourceManager;

class NovaServiceProvider extends ServiceProvider
{
    /**
     * Bootstrap any package services.
     *
     * @return void
     */
    public function boot()
    {
        if ($this->app->runningInConsole()) {
            $this->registerPublishing();
        }

        $this->registerDashboards();
        $this->registerResources();
        $this->registerTools();
        $this->registerCarbonMacros();
        $this->registerCollectionMacros();
        $this->registerJsonVariables();

        Nova::resources([config('nova.actions.resource')]);
    }

    /**
     * Register the package's publishable resources.
     *
     * @return void
     */
    protected function registerPublishing()
    {
        $this->publishes([
            __DIR__.'/Console/stubs/NovaServiceProvider.stub' => app_path('Providers/NovaServiceProvider.php'),
        ], 'nova-provider');

        $this->publishes([
            __DIR__.'/../config/nova.php' => config_path('nova.php'),
        ], 'nova-config');

        $this->publishes([
            __DIR__.'/../public' => public_path('vendor/nova'),
        ], 'nova-assets');

        $this->publishes([
            __DIR__.'/../resources/lang' => resource_path('lang/vendor/nova'),
        ], 'nova-lang');

        $this->publishes([
            __DIR__.'/../resources/views/partials' => resource_path('views/vendor/nova/partials'),
        ], 'nova-views');

        $this->publishes([
            __DIR__.'/../database/migrations' => database_path('migrations'),
        ], 'nova-migrations');
    }

    /**
     * Register the dashboards used by Nova.
     *
     * @return void
     */
    protected function registerDashboards()
    {
        Nova::serving(function (ServingNova $event) {
            Nova::copyDefaultDashboardCards();
        });
    }

    /**
     * Register the package resources such as routes, templates, etc.
     *
     * @return void
     */
    protected function registerResources()
    {
        $this->loadViewsFrom(__DIR__.'/../resources/views', 'nova');
        $this->loadTranslationsFrom(__DIR__.'/../resources/lang', 'nova');
        $this->loadJsonTranslationsFrom(resource_path('lang/vendor/nova'));

        if (Nova::runsMigrations()) {
            $this->loadMigrationsFrom(__DIR__.'/../database/migrations');
        }

        $this->registerRoutes();
    }

    /**
     * Register the package routes.
     *
     * @return void
     */
    protected function registerRoutes()
    {
        Route::group($this->routeConfiguration(), function () {
            $this->loadRoutesFrom(__DIR__.'/../routes/api.php');
        });
    }

    /**
     * Get the Nova route group configuration array.
     *
     * @return array
     */
    protected function routeConfiguration()
    {
        return [
            'namespace' => 'Laravel\Nova\Http\Controllers',
            'domain' => config('nova.domain', null),
            // 'as' => 'nova.api.',
            'prefix' => 'nova-api',
            'middleware' => 'nova',
        ];
    }

    /**
     * Boot the standard Nova tools.
     *
     * @return void
     */
    protected function registerTools()
    {
        Nova::tools([
            new Dashboard,
            new ResourceManager,
        ]);
    }

    /**
     * Register the Nova Carbon macros.
     *
     * @return void
     */
    protected function registerCarbonMacros()
    {
        Carbon::mixin(new Macros\FirstDayOfQuarter);
        Carbon::mixin(new Macros\FirstDayOfPreviousQuarter);
    }

    /**
     * Register the Nova JSON variables.
     *
     * @return void
     */
    protected function registerJsonVariables()
    {
        Nova::serving(function (ServingNova $event) {
            // Load the default Nova translations.
            Nova::translations(
                resource_path('lang/vendor/nova/'.app()->getLocale().'.json')
            );

            Nova::provideToScript([
                'timezone' => config('app.timezone', 'UTC'),
                'translations' => Nova::allTranslations(),
                'userTimezone' => Nova::resolveUserTimezone($event->request),
                'pagination' => config('nova.pagination', 'links'),
                'locale' => config('app.locale', 'en'),
                'algoliaAppId' => config('services.algolia.appId'),
                'algoliaApiKey' => config('services.algolia.apiKey'),
                'version' => Nova::version(),
            ]);
        });
    }

    /**
     * Register any application services.
     *
     * @return void
     */
    public function register()
    {
        $this->commands([
            Console\ActionCommand::class,
            Console\AssetCommand::class,
            Console\BaseResourceCommand::class,
            Console\CardCommand::class,
            Console\CustomFilterCommand::class,
            Console\DashboardCommand::class,
            Console\FilterCommand::class,
            Console\FieldCommand::class,
            Console\InstallCommand::class,
            Console\LensCommand::class,
            Console\PartitionCommand::class,
            Console\PublishCommand::class,
            Console\ResourceCommand::class,
            Console\ResourceToolCommand::class,
            Console\StubPublishCommand::class,
            Console\ThemeCommand::class,
            Console\ToolCommand::class,
            Console\TrendCommand::class,
            Console\UserCommand::class,
            Console\ValueCommand::class,
        ]);
    }

    protected function registerCollectionMacros()
    {
        Collection::macro('isAssoc', function () {
            return Arr::isAssoc($this->toBase()->all());
        });
    }
}
