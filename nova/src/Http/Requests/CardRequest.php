<?php

namespace Laravel\Nova\Http\Requests;

class CardRequest extends NovaRequest
{
    /**
     * Get all of the possible metrics for the request.
     *
     * @return \Illuminate\Support\Collection
     */
    public function availableCards()
    {
        return $this->newResource()->availableCards($this);
    }
}
