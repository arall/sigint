<?php

namespace Laravel\Nova\Http\Requests;

trait CountsResources
{
    /**
     * Build a new count query for the given query.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return \Illuminate\Database\Query\Builder
     */
    public function buildCountQuery($query)
    {
        $baseQuery = $query->toBase();

        if (empty($baseQuery->groups)) {
            return $baseQuery;
        }

        $subQuery = $baseQuery->cloneWithout(
            $baseQuery->unions ? ['orders', 'limit', 'offset'] : ['columns', 'orders', 'limit', 'offset']
        )->cloneWithoutBindings(
            $baseQuery->unions ? ['order'] : ['select', 'order']
        )->selectRaw('1 as exists_temp');

        return $query->getConnection()
            ->query()
            ->fromSub($subQuery, 'count_temp');
    }
}
