<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Laravel\Nova\Http\Requests\NovaRequest;

class UpdatePivotFieldController extends Controller
{
    /**
     * List the pivot fields for the given resource and relation.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function index(NovaRequest $request)
    {
        $model = $request->findModelOrFail();

        $model->setRelation(
            $model->{$request->viaRelationship}()->getPivotAccessor(),
            $model->{$request->viaRelationship}()->withoutGlobalScopes()->findOrFail($request->relatedResourceId)->pivot
        );

        return response()->json(
            $request->newResourceWith($model)->updatePivotFields(
                $request,
                $request->relatedResource
            )->all()
        );
    }
}
