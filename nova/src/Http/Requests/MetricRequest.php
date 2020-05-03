<?php

namespace Laravel\Nova\Http\Requests;

use Laravel\Nova\Metrics\Metric;

class MetricRequest extends NovaRequest
{
    /**
     * Get the metric instance for the given request.
     *
     * @return \Laravel\Nova\Metrics\Metric
     */
    public function metric()
    {
        return $this->availableMetrics()->first(function ($metric) {
            return $this->metric === $metric->uriKey();
        }) ?: abort(404);
    }

    /**
     * Get all of the possible metrics for the request.
     *
     * @return \Illuminate\Support\Collection
     */
    public function availableMetrics()
    {
        return $this->newResource()->availableCards($this)
                ->whereInstanceOf(Metric::class);
    }
}
