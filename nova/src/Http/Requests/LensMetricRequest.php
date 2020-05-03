<?php

namespace Laravel\Nova\Http\Requests;

use Laravel\Nova\Metrics\Metric;

class LensMetricRequest extends MetricRequest
{
    use InteractsWithLenses;

    /**
     * Get all of the possible metrics for the request.
     *
     * @return \Illuminate\Support\Collection
     */
    public function availableMetrics()
    {
        return $this->lens()->availableCards($this)
                ->whereInstanceOf(Metric::class);
    }
}
