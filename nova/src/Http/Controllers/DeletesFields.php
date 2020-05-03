<?php

namespace Laravel\Nova\Http\Controllers;

use Laravel\Nova\Contracts\Deletable;
use Laravel\Nova\DeleteField;
use Laravel\Nova\Http\Requests\NovaRequest;

trait DeletesFields
{
    /**
     * Delete the deletable fields on the given model / resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return void
     */
    protected function forceDeleteFields(NovaRequest $request, $model)
    {
        return $this->deleteFields($request, $model, false);
    }

    /**
     * Delete the deletable fields on the given model / resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @param  bool  $skipSoftDeletes
     * @return void
     */
    protected function deleteFields(NovaRequest $request, $model, $skipSoftDeletes = true)
    {
        if ($skipSoftDeletes && $request->newResourceWith($model)->softDeletes()) {
            return;
        }

        $request->newResourceWith($model)
                    ->detailFields($request)
                    ->whereInstanceOf(Deletable::class)
                    ->filter->isPrunable()
                    ->each(function ($field) use ($request, $model) {
                        DeleteField::forRequest($request, $field, $model);
                    });
    }
}
