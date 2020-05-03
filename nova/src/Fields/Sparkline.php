<?php

namespace Laravel\Nova\Fields;

use Closure;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Metrics\Trend;

class Sparkline extends Field
{
    /**
     * The field's component.
     *
     * @var string
     */
    public $component = 'sparkline-field';

    /**
     * The data used in the chart.
     *
     * @var array|\Closure|\Laravel\Nova\Metrics\Trend
     */
    public $data = [];

    /**
     * The type of chart to use.
     *
     * @var string
     */
    public $chartStyle = 'Line';

    /**
     * Indicates if the element should be shown on the creation view.
     *
     * @var \Closure|bool
     */
    public $showOnCreation = false;

    /**
     * Indicates if the element should be shown on the update view.
     *
     * @var \Closure|bool
     */
    public $showOnUpdate = false;

    /**
     * Set the data for the Spark Line.
     *
     * @param  array|\Closure|\Laravel\Nova\Metrics\Trend  $data
     * @return $this
     */
    public function data($data)
    {
        $this->data = $data;

        return $this;
    }

    /**
     * Get field data.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return array|mixed
     */
    public function getData(NovaRequest $request)
    {
        if ($this->data instanceof Trend) {
            $ranges = $this->data->ranges();
            $defaultRange = array_key_first($ranges);

            $result = $this->data->calculate(
                $request->merge([
                    'range' => $defaultRange,
                    'resourceId' => $this->data->component,
                ])
            );

            return array_values($this->data->calculate($request)->trend ?? []);
        } elseif ($this->data instanceof Closure) {
            return call_user_func($this->data, $request);
        }

        return $this->data;
    }

    /**
     * Format the sparkline as a bar.
     *
     * @return $this
     */
    public function asBarChart()
    {
        $this->chartStyle = 'Bar';

        return $this;
    }

    /**
     * Set the component height.
     *
     * @param  int  $height
     * @return $this
     */
    public function height($height)
    {
        return $this->withMeta([
            __FUNCTION__ => $height,
        ]);
    }

    /**
     * Set the component width.
     *
     * @param  int  $width
     * @return $this
     */
    public function width($width)
    {
        return $this->withMeta([
            __FUNCTION__ => $width,
        ]);
    }

    /**
     * Prepare the element for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'chartStyle' => $this->chartStyle,
            'data' => $this->getData(app(NovaRequest::class)),
        ]);
    }
}
