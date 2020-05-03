<?php

namespace Laravel\Nova\Metrics;

use Cake\Chronos\Chronos;
use DateTime;
use DateTimeZone;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Query\Expression;

abstract class TrendDateExpression extends Expression
{
    /**
     * The query builder being used to build the trend.
     *
     * @var \Illuminate\Database\Query\Builder
     */
    public $query;

    /**
     * The column being measured.
     *
     * @var string
     */
    public $column;

    /**
     * The unit being measured.
     *
     * @var string
     */
    public $unit;

    /**
     * The users's local timezone.
     *
     * @var string
     */
    public $timezone;

    /**
     * Create a new raw query expression.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @param  string  $column
     * @param  string  $unit
     * @param  string  $timezone
     * @return void
     */
    public function __construct(Builder $query, $column, $unit, $timezone)
    {
        $this->unit = $unit;
        $this->query = $query;
        $this->column = $column;
        $this->timezone = $timezone;
    }

    /**
     * Get the timezone offset for the user's timezone.
     *
     * @return int
     */
    public function offset()
    {
        if ($this->timezone) {
            return (new DateTime(Chronos::now()->format('Y-m-d H:i:s'), new DateTimeZone($this->timezone)))->getOffset() / 60 / 60;
        }

        return 0;
    }

    /**
     * Wrap the given value using the query's grammar.
     *
     * @param  string  $value
     * @return string
     */
    protected function wrap($value)
    {
        return $this->query->getQuery()->getGrammar()->wrap($value);
    }
}
