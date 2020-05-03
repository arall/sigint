<?php

namespace Laravel\Nova\Metrics;

class SqlSrvTrendDateExpression extends TrendDateExpression
{
    /**
     * Get the value of the expression.
     *
     * @return mixed
     */
    public function getValue()
    {
        $column = $this->wrap($this->column);
        $offset = $this->offset();

        if ($offset >= 0) {
            $interval = $offset;
        } else {
            $interval = '-'.($offset * -1);
        }

        $date = "DATEADD(hour, {$interval}, {$column})";

        switch ($this->unit) {
            case 'month':
                return "FORMAT({$date}, 'yyyy-MM')";
            case 'week':
                return "concat(
                    YEAR({$date}),
                    '-',
                    datepart(ISO_WEEK, {$date})
                )";
            case 'day':
                return "FORMAT({$date}, 'yyyy-MM-dd')";
            case 'hour':
                return "FORMAT({$date}, 'yyyy-MM-dd HH:00')";
            case 'minute':
                return "FORMAT({$date}, 'yyyy-MM-dd HH:mm:00')";
        }
    }
}
