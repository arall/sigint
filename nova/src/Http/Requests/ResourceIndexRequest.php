<?php

namespace Laravel\Nova\Http\Requests;

class ResourceIndexRequest extends NovaRequest
{
    use CountsResources, QueriesResources;

    /**
     * Get the count of the resources.
     *
     * @return int
     */
    public function toCount()
    {
        return $this->buildCountQuery($this->toQuery())->count();
    }
}
