<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Http\Requests\LensCardRequest;

class LensCardController extends Controller
{
    /**
     * List the cards for the given lens.
     *
     * @param  \Laravel\Nova\Http\Requests\LensCardRequest  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function index(LensCardRequest $request)
    {
        return response()->json(
            $request->availableCards()
        );
    }
}
