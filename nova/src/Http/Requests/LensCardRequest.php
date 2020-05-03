<?php

namespace Laravel\Nova\Http\Requests;

class LensCardRequest extends CardRequest
{
    use InteractsWithLenses;

    /**
     * Get all of the possible metrics for the request.
     *
     * @return \Illuminate\Support\Collection
     */
    public function availableCards()
    {
        return $this->lens()->availableCards($this);
    }
}
