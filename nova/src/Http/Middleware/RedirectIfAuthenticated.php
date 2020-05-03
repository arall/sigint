<?php

namespace Laravel\Nova\Http\Middleware;

use Closure;
use Illuminate\Support\Facades\Auth;
use Laravel\Nova\Nova;

class RedirectIfAuthenticated
{
    /**
     * Handle an incoming request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Closure  $next
     * @param  string|null  $guard
     * @return mixed
     */
    public function handle($request, Closure $next, $guard = null)
    {
        if (Auth::guard($guard)->check()) {
            return redirect(Nova::path());
        }

        return $next($request);
    }
}
