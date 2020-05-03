<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Routing\Controller;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Http\Requests\LensRequest;

class LensController extends Controller
{
    /**
     * List the lenses for the given resource.
     *
     * @param  \Laravel\Nova\Http\Requests\LensRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function index(LensRequest $request)
    {
        return $request->availableLenses();
    }

    /**
     * Get the specified lens and its resources.
     *
     * @param  \Laravel\Nova\Http\Requests\LensRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function show(LensRequest $request)
    {
        $lens = $request->lens();

        $paginator = $lens->query($request, $request->newQuery());

        if ($paginator instanceof Builder) {
            $paginator = $paginator->simplePaginate($request->perPage ?? $request->resource()::perPageOptions()[0]);
        }

        return response()->json([
            'name' => $request->lens()->name(),
            'resources' => $request->toResources($paginator->getCollection()),
            'prev_page_url' => $paginator->previousPageUrl(),
            'next_page_url' => $paginator->nextPageUrl(),
            'per_page' => $paginator->perPage(),
            'per_page_options' => $request->resource()::perPageOptions(),
            'softDeletes' => $request->resourceSoftDeletes(),
            'hasId' => $lens->availableFields($request)->whereInstanceOf(ID::class)->isNotEmpty(),
        ]);
    }
}
