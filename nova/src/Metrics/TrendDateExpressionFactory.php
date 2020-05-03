<?php

namespace Laravel\Nova\Metrics;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Traits\Macroable;
use InvalidArgumentException;

class TrendDateExpressionFactory
{
    use Macroable;

    /**
     * Create a new trend expression instance.
     *
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @param  string  $column
     * @param  string  $unit
     * @param  string  $timezone
     * @return \Laravel\Nova\Metrics\TrendDateExpression
     */
    public static function make(Builder $query, $column, $unit, $timezone)
    {
        $driver = $query->getConnection()->getDriverName();

        if (static::hasMacro($driver)) {
            return static::$driver($query, $column, $unit, $timezone);
        }

        switch ($driver) {
            case 'sqlite':
                return new SqliteTrendDateExpression($query, $column, $unit, $timezone);
            case 'mysql':
            case 'mariadb':
                return new MySqlTrendDateExpression($query, $column, $unit, $timezone);
            case 'pgsql':
                return new PostgresTrendDateExpression($query, $column, $unit, $timezone);
            case 'sqlsrv':
                return new SqlSrvTrendDateExpression($query, $column, $unit, $timezone);
            default:
                throw new InvalidArgumentException('Trend metric helpers are not supported for this database.');
        }
    }
}
