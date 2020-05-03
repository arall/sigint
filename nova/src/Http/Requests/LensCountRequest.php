<?php

namespace Laravel\Nova\Http\Requests;

use Exception;
use Illuminate\Database\Eloquent\Builder;
use Laravel\Nova\Exceptions\LensCountException;

class LensCountRequest extends NovaRequest
{
    use CountsResources, InteractsWithLenses;

    /**
     * Get the count of the lens resources.
     *
     * @return int
     */
    public function toCount()
    {
        try {
            return $this->buildCountQuery($this->toQuery())->count();
        } catch (Exception $e) {
            report($e);
        }

        return 0;
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
                throw new LensCountException('Lens must return an Eloquent query instance in order to count lens resources.');
            }
        });
    }
}
