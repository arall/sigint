<?php

namespace Laravel\Nova\Http\Requests;

trait QueriesResources
{
    use DecodesFilters;

    /**
     * Transform the request into a query.
     *
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function toQuery()
    {
        $resource = $this->resource();

        return $resource::buildIndexQuery(
            $this, $this->newQuery(), $this->search,
            $this->filters()->all(), $this->orderings(), $this->trashed()
        );
    }

    /**
     * Get a new query builder for the underlying model.
     *
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function newQuery()
    {
        if (! $this->viaRelationship()) {
            return $this->model()->newQuery();
        }

        return forward_static_call([$this->viaResource(), 'newModel'])
                        ->newQueryWithoutScopes()->findOrFail(
                            $this->viaResourceId
                        )->{$this->viaRelationship}();
    }

    /**
     * Get a new query builder for the underlying model.
     *
     * @return \Illuminate\Database\Eloquent\Builder
     */
    public function newQueryWithoutScopes()
    {
        if (! $this->viaRelationship()) {
            return $this->model()->newQueryWithoutScopes();
        }

        return forward_static_call([$this->viaResource(), 'newModel'])
                    ->newQueryWithoutScopes()->findOrFail(
                        $this->viaResourceId
                    )->{$this->viaRelationship}()->withoutGlobalScopes();
    }

    /**
     * Get the orderings for the request.
     *
     * @return array
     */
    public function orderings()
    {
        return ! empty($this->orderBy)
                        ? [$this->orderBy => $this->orderByDirection]
                        : [];
    }

    /**
     * Get the trashed status of the request.
     *
     * @return string
     */
    protected function trashed()
    {
        return $this->trashed;
    }
}
