<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Http\Requests\NovaRequest;

class AttachableController extends Controller
{
    /**
     * List the available related resources for a given resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function index(NovaRequest $request)
    {
        $field = $request->newResource()
                    ->availableFields($request)
                    ->filterForManyToManyRelations()
                    ->firstWhere('resourceName', $request->field);

        $withTrashed = $this->shouldIncludeTrashed(
            $request, $associatedResource = $field->resourceClass
        );

        $parentResource = $request->findResourceOrFail();

        return [
            'resources' => $field->buildAttachableQuery($request, $withTrashed)->get()
                        ->mapInto($field->resourceClass)
                        ->filter(function ($resource) use ($request, $parentResource) {
                            return $parentResource->authorizedToAttach($request, $resource->resource);
                        })
                        ->map(function ($resource) use ($request, $field) {
                            return $field->formatAttachableResource($request, $resource);
                        })->sortBy('display', SORT_NATURAL | SORT_FLAG_CASE)->values(),
            'withTrashed' => $withTrashed,
            'softDeletes' => $associatedResource::softDeletes(),
        ];
    }

    /**
     * Determine if the query should include trashed models.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  string  $associatedResource
     * @return bool
     */
    protected function shouldIncludeTrashed(NovaRequest $request, $associatedResource)
    {
        if ($request->withTrashed === 'true') {
            return true;
        }

        $associatedModel = $associatedResource::newModel();

        if ($request->current && $associatedResource::softDeletes()) {
            $associatedModel = $associatedModel->newQueryWithoutScopes()->find($request->current);

            return $associatedModel ? $associatedModel->trashed() : false;
        }

        return false;
    }
}
