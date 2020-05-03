<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Fields\Downloadable;
use Laravel\Nova\Http\Requests\NovaRequest;

class FieldDownloadController extends Controller
{
    /**
     * Download the given field's contents.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function show(NovaRequest $request)
    {
        $resource = $request->findResourceOrFail();

        $resource->authorizeToView($request);

        return $resource->detailFields($request)
                    ->whereInstanceOf(Downloadable::class)
                    ->findFieldByAttribute($request->field, function () {
                        abort(404);
                    })
                    ->toDownloadResponse($request, $resource);
    }
}
