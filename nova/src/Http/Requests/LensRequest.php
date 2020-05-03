<?php

namespace Laravel\Nova\Http\Requests;

use Illuminate\Support\Collection;

class LensRequest extends NovaRequest
{
    use DecodesFilters, InteractsWithLenses;

    /**
     * Whether to include the table order prefix.
     *
     * @var bool
     */
    protected $tableOrderPrefix = true;

    /**
     * Apply the specified filters to the given query.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function withFilters($query)
    {
        return $this->filter($query);
    }

    /**
     * Apply the specified filters to the given query.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function filter($query)
    {
        $this->filters()->each->__invoke($this, $query);

        return $query;
    }

    /**
     * Apply the specified ordering to the given query.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function withOrdering($query)
    {
        if (! $this->orderBy || ! $this->orderByDirection) {
            return $query;
        }

        if ($this->lens()->resolveFields($this)->findFieldByAttribute($this->orderBy)) {
            return $query->orderBy(
                ($this->tableOrderPrefix ? $query->getModel()->getTable().'.' : '').$this->orderBy,
                $this->orderByDirection === 'asc' ? 'asc' : 'desc'
            );
        }

        return $query;
    }

    /**
     * Disable prepending of the table order.
     *
     * @return $this
     */
    public function withoutTableOrderPrefix()
    {
        $this->tableOrderPrefix = false;

        return $this;
    }

    /**
     * Get all of the possibly available filters for the request.
     *
     * @return \Illuminate\Support\Collection
     */
    protected function availableFilters()
    {
        return $this->lens()->availableFilters($this);
    }

    /**
     * Map the given models to the appropriate resource for the request.
     *
     * @param  \Illuminate\Support\Collection  $models
     * @return \Illuminate\Support\Collection
     */
    public function toResources(Collection $models)
    {
        $resource = $this->resource();

        $lens = get_class($this->lens());

        return $models->map(function ($model) use ($resource, $lens) {
            return (new $resource($model))->serializeForIndex(
                $this, (new $lens($model))->resolveFields($this)
            );
        });
    }
}
