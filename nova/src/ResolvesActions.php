<?php

namespace Laravel\Nova;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\BelongsToMany;
use Laravel\Nova\Fields\MorphToMany;
use Laravel\Nova\Http\Requests\NovaRequest;

trait ResolvesActions
{
    /**
     * Get the actions that are available for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Support\Collection
     */
    public function availableActions(NovaRequest $request)
    {
        return $this->resolveActions($request)->filter->authorizedToSee($request)->values();
    }

    /**
     * Get the actions for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Support\Collection
     */
    public function resolveActions(NovaRequest $request)
    {
        return collect(array_values($this->filter($this->actions($request))));
    }

    /**
     * Get the "pivot" actions that are available for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Support\Collection
     */
    public function availablePivotActions(NovaRequest $request)
    {
        return $this->resolvePivotActions($request)->filter->authorizedToSee($request)->values();
    }

    /**
     * Get the "pivot" actions for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Support\Collection
     */
    public function resolvePivotActions(NovaRequest $request)
    {
        if ($request->viaRelationship()) {
            return collect(array_values($this->filter($this->getPivotActions($request))));
        }

        return collect();
    }

    /**
     * Get the "pivot" actions for the given request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return array
     */
    protected function getPivotActions(NovaRequest $request)
    {
        $field = $this->availableFields($request)->first(function ($field) use ($request) {
            return isset($field->resourceName) &&
                   $field->resourceName == $request->viaResource &&
                   ($field instanceof BelongsToMany || $field instanceof MorphToMany);
        });

        if ($field && isset($field->actionsCallback)) {
            return array_values(call_user_func($field->actionsCallback, $request));
        }

        return [];
    }

    /**
     * Get the actions available on the entity.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function actions(Request $request)
    {
        return [];
    }
}
