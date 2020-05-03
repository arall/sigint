<?php

namespace Laravel\Nova\Metrics;

abstract class RangedMetric extends Metric
{
    /**
     * The ranges available for the metric.
     *
     * @var array
     */
    public $ranges = [];

    /**
     * The selected range key.
     *
     * @var string|null
     */
    public $selectedRangeKey;

    /**
     * Get the ranges available for the metric.
     *
     * @return array
     */
    public function ranges()
    {
        return $this->ranges;
    }

    /**
     * Set the default range.
     *
     * @param string $key
     *
     * @return $this
     */
    public function defaultRange($key)
    {
        $this->selectedRangeKey = $key;

        return $this;
    }

    /**
     * Prepare the metric for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'selectedRangeKey' => $this->selectedRangeKey,
            'ranges' => collect($this->ranges() ?? [])->map(function ($range, $key) {
                return ['label' => $range, 'value' => $key];
            })->values()->all(),
        ]);
    }
}
