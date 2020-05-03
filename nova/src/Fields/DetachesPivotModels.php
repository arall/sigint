<?php

namespace Laravel\Nova\Fields;

use Laravel\Nova\Contracts\Deletable;
use Laravel\Nova\DeleteField;
use Laravel\Nova\Nova;

trait DetachesPivotModels
{
    /**
     * Get the pivot record detachment callback for the field.
     *
     * @return \Closure
     */
    protected function detachmentCallback()
    {
        return function ($request, $model) {
            foreach ($model->{$this->attribute}()->withoutGlobalScopes()->get() as $related) {
                $resource = Nova::resourceForModel($related);

                $resource = new $resource($related);

                $pivot = $related->{$model->{$this->attribute}()->getPivotAccessor()};

                $pivotFields = $resource->resolvePivotFields($request, $request->resource);

                $pivotFields->whereInstanceOf(Deletable::class)
                        ->filter->isPrunable()
                        ->each(function ($field) use ($request, $pivot) {
                            DeleteField::forRequest($request, $field, $pivot)->save();
                        });

                $pivot->delete();
            }

            return true;
        };
    }
}
