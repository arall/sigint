<?php

namespace Laravel\Nova\Metrics;

class MySqlTrendDateExpression extends TrendDateExpression
{
    /**
     * Get the value of the expression.
     *
     * @return mixed
     */
    public function getValue()
    {
        $offset = $this->offset();

        if ($offset > 0) {
            $interval = '+ INTERVAL '.$offset.' HOUR';
        } elseif ($offset === 0) {
            $interval = '';
        } else {
            $interval = '- INTERVAL '.($offset * -1).' HOUR';
        }

        switch ($this->unit) {
            case 'month':
                return "date_format({$this->wrap($this->column)} {$interval}, '%Y-%m')";
            case 'week':
                return "date_format({$this->wrap($this->column)} {$interval}, '%x-%v')";
            case 'day':
                return "date_format({$this->wrap($this->column)} {$interval}, '%Y-%m-%d')";
            case 'hour':
                return "date_format({$this->wrap($this->column)} {$interval}, '%Y-%m-%d %H:00')";
            case 'minute':
                return "date_format({$this->wrap($this->column)} {$interval}, '%Y-%m-%d %H:%i:00')";
        }
    }
}
