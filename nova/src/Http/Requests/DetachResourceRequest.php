<?php

namespace Laravel\Nova\Http\Requests;

use Closure;
use Illuminate\Support\Collection;

class DetachResourceRequest extends DeletionRequest
{
    /**
     * Get the selected models for the action in chunks.
     *
     * @param  int  $count
     * @param  \Closure  $callback
     * @return mixed
     */
    public function chunks($count, Closure $callback)
    {
        $parentResource = $this->findParentResourceOrFail();

        $this->toSelectedResourceQuery()->when(! $this->forAllMatchingResources(), function ($query) {
            $query->whereKey($this->resources);
        })->latest($this->model()->getQualifiedKeyName())->chunkById($count, function ($models) use ($callback, $parentResource) {
            $models = $this->detachableModels($models, $parentResource);

            if ($models->isNotEmpty()) {
                $callback($models);
            }
        });
    }

    /**
     * Get the models that may be detached.
     *
     * @param  \Illuminate\Support\Collection  $models
     * @param  \Laravel\Nova\Resource  $parentResource
     * @return \Illuminate\Support\Collection
     */
    protected function detachableModels(Collection $models, $parentResource)
    {
        return $models->filter(function ($model) use ($parentResource) {
            return $parentResource->authorizedToDetach($this, $model, $this->viaRelationship);
        });
    }
}
