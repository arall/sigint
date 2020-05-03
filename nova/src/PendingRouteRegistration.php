<?php

namespace Laravel\Nova;

use Illuminate\Support\Facades\Event;
use Illuminate\Support\Facades\Route;
use Laravel\Nova\Events\NovaServiceProviderRegistered;

class PendingRouteRegistration
{
    /**
     * Indicates if the routes have been registered.
     *
     * @var bool
     */
    protected $registered = false;

    /**
     * Register the Nova authentication routes.
     *
     * @param  array  $middleware
     * @return $this
     */
    public function withAuthenticationRoutes($middleware = ['web'])
    {
        Route::namespace('Laravel\Nova\Http\Controllers')
            ->domain(config('nova.domain', null))
            ->middleware($middleware)
            ->prefix(Nova::path())
            ->group(function () {
                Route::get('/login', 'LoginController@showLoginForm');
                Route::post('/login', 'LoginController@login')->name('nova.login');
            });

        Route::namespace('Laravel\Nova\Http\Controllers')
            ->domain(config('nova.domain', null))
            ->middleware(config('nova.middleware', []))
            ->prefix(Nova::path())
            ->group(function () {
                Route::get('/logout', 'LoginController@logout')->name('nova.logout');
            });

        return $this;
    }

    /**
     * Register the Nova password reset routes.
     *
     * @param  array  $middleware
     * @return $this
     */
    public function withPasswordResetRoutes($middleware = ['web'])
    {
        Nova::$resetsPasswords = true;

        Route::namespace('Laravel\Nova\Http\Controllers')
            ->domain(config('nova.domain', null))
            ->middleware($middleware)
            ->prefix(Nova::path())
            ->group(function () {
                Route::get('/password/reset', 'ForgotPasswordController@showLinkRequestForm')->name('nova.password.request');
                Route::post('/password/email', 'ForgotPasswordController@sendResetLinkEmail')->name('nova.password.email');
                Route::get('/password/reset/{token}', 'ResetPasswordController@showResetForm')->name('nova.password.reset');
                Route::post('/password/reset', 'ResetPasswordController@reset');
            });

        return $this;
    }

    /**
     * Register the Nova routes.
     *
     * @return void
     */
    public function register()
    {
        $this->registered = true;

        $defineRouterControllerRoutes = function () {
            Route::middleware(config('nova.middleware', []))
                ->domain(config('nova.domain', null))
                ->group(function () {
                    Route::get(Nova::path(), 'Laravel\Nova\Http\Controllers\RouterController@show')->name('nova.index');
                });

            Route::middleware(config('nova.middleware', []))
                ->domain(config('nova.domain', null))
                ->prefix(Nova::path())
                ->get('/{view}', 'Laravel\Nova\Http\Controllers\RouterController@show')
                 ->where('view', '.*');
        };

        if (app()->runningInConsole() && ! app()->runningUnitTests()) {
            app()->booted($defineRouterControllerRoutes);
        } else {
            Event::listen(NovaServiceProviderRegistered::class, $defineRouterControllerRoutes);
        }
    }

    /**
     * Handle the object's destruction and register the router route.
     *
     * @return void
     */
    public function __destruct()
    {
        if (! $this->registered) {
            $this->register();
        }
    }
}
