<?php

namespace App\Http\Middleware;

use Closure;

class AuthenticateWithToken
{
    /**
     * Handle an incoming request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Closure  $next
     * @return mixed
     */
    public function handle($request, Closure $next)
    {
        $token = $request->bearerToken();
        if ($token !== env('API_KEY')) {
            return response()->json('Unauthorized', 401);
        }

        return $next($request);
    }
}
