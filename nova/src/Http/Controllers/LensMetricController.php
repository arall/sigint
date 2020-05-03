<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Http\Requests\LensMetricRequest;

class LensMetricController extends Controller
{
    /**
     * List the metrics for the given resource.
     *
     * @param  \Laravel\Nova\Http\Requests\LensMetricRequest  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function index(LensMetricRequest $request)
    {
        return response()->json(
            $request->availableMetrics()
        );
    }

    /**
     * Get the specified metric's value.
     *
     * @param  \Laravel\Nova\Http\Requests\LensMetricRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function show(LensMetricRequest $request)
    {
        return response()->json([
            'value' => $request->metric()->resolve($request),
        ]);
    }
}
