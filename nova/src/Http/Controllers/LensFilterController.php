<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Http\Requests\NovaRequest;

class LensFilterController extends Controller
{
    /**
     * List the lenses for the given resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function index(NovaRequest $request)
    {
        $lenses = $request->newResource()->availableLenses($request);

        $lens = $lenses->first(function ($lens) use ($request) {
            return $lens->uriKey() === $request->lens;
        });

        return response()->json($lens->availableFilters($request));
    }
}
