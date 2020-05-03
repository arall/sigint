<?php

namespace Laravel\Nova\Http\Requests;

use Closure;
use Illuminate\Database\Eloquent\Builder;
use LogicException;

class LensResourceDeletionRequest extends NovaRequest
{
    use InteractsWithLenses, QueriesResources;

    /**
     * Get the selected models for the action in chunks.
     *
     * @param  int  $count
     * @param  \Closure  $callback
     * @param  \Closure  $authCallback
     * @return mixed
     */
    protected function chunkWithAuthorization($count, Closure $callback, Closure $authCallback)
    {
        $this->toSelectedResourceQuery()->when(! $this->forAllMatchingResources(), function ($query) {
            $query->whereKey($this->resources);
        })->tap(function ($query) {
            $query->getQuery()->orders = [];
        })->chunkById($count, function ($models) use ($callback, $authCallback) {
            $models = $authCallback($models);

            if ($models->isNotEmpty()) {
                $callback($models);
            }
        });
    }

    /**
     * Get the query for the models that were selected by the user.
     *
     * @return \Illuminate\Database\Eloquent\Builder
     */
    protected function toSelectedResourceQuery()
    {
        return $this->forAllMatchingResources()
                    ? $this->toQuery()
                    : $this->newQueryWithoutScopes();
    }

    /**
     * Transform the request into a query.
     *
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function toQuery()
    {
        return tap($this->lens()->query(LensRequest::createFrom($this), $this->newQuery()), function ($query) {
            if (! $query instanceof Builder) {
                throw new LogicException('Lens must return an Eloquent query instance in order to perform this action.');
            }
        });
    }

    /**
     * Determine if the request is for all matching resources.
     *
     * @return bool
     */
    public function forAllMatchingResources()
    {
        return $this->resources === 'all';
    }
}
