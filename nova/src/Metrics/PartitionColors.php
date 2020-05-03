<?php

namespace Laravel\Nova\Metrics;

class PartitionColors
{
    /**
     * The color array to use for the chart.
     *
     * @var array
     */
    public $colors;

    /**
     * The pointer to the current color in the chart array.
     *
     * @var int
     */
    private $pointer = 0;

    /**
     * Create a new instance.
     *
     * @param  array  $colors
     * @return void
     */
    public function __construct($colors = [])
    {
        $this->colors = $colors;
    }

    /**
     * Get the color found at the given label key.
     *
     * @param  string|int  $label
     * @return void
     */
    public function get($label)
    {
        return $this->colors[$label] ?? $this->next();
    }

    /**
     * Return the next color in the color list.
     *
     * @return null|string
     */
    protected function next()
    {
        return blank($this->colors) ? null :
            tap($this->colors[
                $this->pointer % count($this->colors)
            ], function () {
                $this->pointer++;
            });
    }
}
