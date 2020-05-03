<?php

namespace Laravel\Nova\Http\Controllers;

use DateTime;
use Laravel\Nova\Http\Requests\NovaRequest;

class MorphedResourceAttachController extends ResourceAttachController
{
    /**
     * Initialize a fresh pivot model for the relationship.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Relations\MorphToMany  $relationship
     * @return \Illuminate\Database\Eloquent\Pivot
     */
    protected function initializePivot(NovaRequest $request, $relationship)
    {
        ($pivot = $relationship->newPivot())->forceFill([
            $relationship->getForeignPivotKeyName() => $request->resourceId,
            $relationship->getRelatedPivotKeyName() => $request->input($request->relatedResource),
            $relationship->getMorphType() => $request->findModelOrFail()->{$request->viaRelationship}()->getMorphClass(),
        ]);

        if ($relationship->withTimestamps) {
            $pivot->forceFill([
                $relationship->createdAt() => new DateTime,
                $relationship->updatedAt() => new DateTime,
            ]);
        }

        return $pivot;
    }
}
