<?php

namespace Laravel\Nova\Metrics;

use Cake\Chronos\Chronos;
use DateTime;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;
use Laravel\Nova\Nova;

abstract class Trend extends RangedMetric
{
    /**
     * Trend metric unit constants.
     */
    const BY_MONTHS = 'month';
    const BY_WEEKS = 'week';
    const BY_DAYS = 'day';
    const BY_HOURS = 'hour';
    const BY_MINUTES = 'minute';

    /**
     * The element's component.
     *
     * @var string
     */
    public $component = 'trend-metric';

    /**
     * Create a new trend metric result.
     *
     * @param  string|null  $value
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function result($value = null)
    {
        return new TrendResult($value);
    }

    /**
     * Return a value result showing a count aggregate over months.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function countByMonths($request, $model, $column = null)
    {
        return $this->count($request, $model, self::BY_MONTHS, $column);
    }

    /**
     * Return a value result showing a count aggregate over weeks.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function countByWeeks($request, $model, $column = null)
    {
        return $this->count($request, $model, self::BY_WEEKS, $column);
    }

    /**
     * Return a value result showing a count aggregate over days.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function countByDays($request, $model, $column = null)
    {
        return $this->count($request, $model, self::BY_DAYS, $column);
    }

    /**
     * Return a value result showing a count aggregate over hours.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function countByHours($request, $model, $column = null)
    {
        return $this->count($request, $model, self::BY_HOURS, $column);
    }

    /**
     * Return a value result showing a count aggregate over minutes.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function countByMinutes($request, $model, $column = null)
    {
        return $this->count($request, $model, self::BY_MINUTES, $column);
    }

    /**
     * Return a value result showing a count aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string|null  $column
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function count($request, $model, $unit, $column = null)
    {
        $resource = $model instanceof Builder ? $model->getModel() : new $model;

        $column = $column ?? $resource->getCreatedAtColumn();

        return $this->aggregate($request, $model, $unit, 'count', $resource->getQualifiedKeyName(), $column);
    }

    /**
     * Return a value result showing a average aggregate over months.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function averageByMonths($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MONTHS, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a average aggregate over weeks.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function averageByWeeks($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_WEEKS, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a average aggregate over days.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function averageByDays($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_DAYS, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a average aggregate over hours.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function averageByHours($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_HOURS, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a average aggregate over minutes.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function averageByMinutes($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MINUTES, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a average aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function average($request, $model, $unit, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, $unit, 'avg', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over months.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sumByMonths($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MONTHS, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over weeks.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sumByWeeks($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_WEEKS, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over days.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sumByDays($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_DAYS, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over hours.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sumByHours($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_HOURS, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over minutes.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sumByMinutes($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MINUTES, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a sum aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function sum($request, $model, $unit, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, $unit, 'sum', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over months.
     *
     * @param  \Illuminate\Http\Request $request
     * @param  \Illuminate\Database\Eloquent\Builder|string $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return TrendResult
     */
    public function maxByMonths($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MONTHS, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over weeks.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function maxByWeeks($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_WEEKS, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over days.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function maxByDays($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_DAYS, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over hours.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function maxByHours($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_HOURS, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over minutes.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function maxByMinutes($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MINUTES, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a max aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function max($request, $model, $unit, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, $unit, 'max', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over months.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function minByMonths($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MONTHS, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over weeks.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function minByWeeks($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_WEEKS, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over days.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function minByDays($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_DAYS, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over hours.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function minByHours($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_HOURS, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over minutes.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function minByMinutes($request, $model, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, self::BY_MINUTES, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a min aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    public function min($request, $model, $unit, $column, $dateColumn = null)
    {
        return $this->aggregate($request, $model, $unit, 'min', $column, $dateColumn);
    }

    /**
     * Return a value result showing a aggregate over time.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  \Illuminate\Database\Eloquent\Builder|string  $model
     * @param  string  $unit
     * @param  string  $function
     * @param  string  $column
     * @param  string  $dateColumn
     * @return \Laravel\Nova\Metrics\TrendResult
     */
    protected function aggregate($request, $model, $unit, $function, $column, $dateColumn = null)
    {
        $query = $model instanceof Builder ? $model : (new $model)->newQuery();

        $timezone = Nova::resolveUserTimezone($request) ?? $request->timezone;

        $expression = (string) TrendDateExpressionFactory::make(
            $query, $dateColumn = $dateColumn ?? $query->getModel()->getCreatedAtColumn(),
            $unit, $timezone
        );

        $possibleDateResults = $this->getAllPossibleDateResults(
            $startingDate = $this->getAggregateStartingDate($request, $unit),
            $endingDate = Chronos::now(),
            $unit,
            $timezone,
            $request->twelveHourTime === 'true'
        );

        $wrappedColumn = $query->getQuery()->getGrammar()->wrap($column);

        $results = $query
                ->select(DB::raw("{$expression} as date_result, {$function}({$wrappedColumn}) as aggregate"))
                ->whereBetween($dateColumn, [$startingDate, $endingDate])
                ->groupBy(DB::raw($expression))
                ->orderBy('date_result')
                ->get();

        $results = array_merge($possibleDateResults, $results->mapWithKeys(function ($result) use ($request, $unit) {
            return [$this->formatAggregateResultDate(
                $result->date_result, $unit, $request->twelveHourTime === 'true'
            ) => round($result->aggregate, 0)];
        })->all());

        if (count($results) > $request->range) {
            array_shift($results);
        }

        return $this->result()->trend(
            $results
        );
    }

    /**
     * Determine the proper aggregate strating date.
     *
     * @param  \Illuminate\Http\Request  $request
     * @param  string  $unit
     * @return \Cake\Chronos\Chronos
     */
    protected function getAggregateStartingDate($request, $unit)
    {
        $now = Chronos::now();

        switch ($unit) {
            case 'month':
                return $now->subMonths($request->range - 1)->firstOfMonth()->setTime(0, 0);

            case 'week':
                return $now->subWeeks($request->range - 1)->startOfWeek()->setTime(0, 0);

            case 'day':
                return $now->subDays($request->range - 1)->setTime(0, 0);

            case 'hour':
                return with($now->subHours($request->range - 1), function ($now) {
                    return $now->setTimeFromTimeString($now->hour.':00');
                });

            case 'minute':
                return with($now->subMinutes($request->range - 1), function ($now) {
                    return $now->setTimeFromTimeString($now->hour.':'.$now->minute.':00');
                });

            default:
                throw new InvalidArgumentException('Invalid trend unit provided.');
        }
    }

    /**
     * Format the aggregate result date into a proper string.
     *
     * @param  string  $result
     * @param  string  $unit
     * @param  bool  $twelveHourTime
     * @return string
     */
    protected function formatAggregateResultDate($result, $unit, $twelveHourTime)
    {
        switch ($unit) {
            case 'month':
                return $this->formatAggregateMonthDate($result);

            case 'week':
                return $this->formatAggregateWeekDate($result);

            case 'day':
                return with(Chronos::createFromFormat('Y-m-d', $result), function ($date) {
                    return __($date->format('F')).' '.$date->format('j').', '.$date->format('Y');
                });

            case 'hour':
                return with(Chronos::createFromFormat('Y-m-d H:00', $result), function ($date) use ($twelveHourTime) {
                    return $twelveHourTime
                            ? __($date->format('F')).' '.$date->format('j').' - '.$date->format('g:00 A')
                            : __($date->format('F')).' '.$date->format('j').' - '.$date->format('G:00');
                });

            case 'minute':
                return with(Chronos::createFromFormat('Y-m-d H:i:00', $result), function ($date) use ($twelveHourTime) {
                    return $twelveHourTime
                            ? __($date->format('F')).' '.$date->format('j').' - '.$date->format('g:i A')
                            : __($date->format('F')).' '.$date->format('j').' - '.$date->format('G:i');
                });
        }
    }

    /**
     * Format the aggregate month result date into a proper string.
     *
     * @param  string  $result
     * @return string
     */
    protected function formatAggregateMonthDate($result)
    {
        [$year, $month] = explode('-', $result);

        return with(Chronos::create((int) $year, (int) $month, 1), function ($date) {
            return __($date->format('F')).' '.$date->format('Y');
        });
    }

    /**
     * Format the aggregate week result date into a proper string.
     *
     * @param  string  $result
     * @return string
     */
    protected function formatAggregateWeekDate($result)
    {
        [$year, $week] = explode('-', $result);

        $isoDate = (new DateTime)->setISODate($year, $week)->setTime(0, 0);

        [$startingDate, $endingDate] = [
            Chronos::instance($isoDate),
            Chronos::instance($isoDate)->endOfWeek(),
        ];

        return __($startingDate->format('F')).' '.$startingDate->format('j').' - '.
               __($endingDate->format('F')).' '.$endingDate->format('j');
    }

    /**
     * Get all of the possbile date results for the given units.
     *
     * @param  \Cake\Chronos\Chronos  $startingDate
     * @param  \Cake\Chronos\Chronos  $endingDate
     * @param  string  $unit
     * @param  mixed  $timezone
     * @param  bool  $twelveHourTime
     * @return array
     */
    protected function getAllPossibleDateResults(Chronos $startingDate, Chronos $endingDate,
                                                 $unit, $timezone, $twelveHourTime)
    {
        $nextDate = $startingDate;

        if (! empty($timezone)) {
            $nextDate = $startingDate->setTimezone($timezone);
            $endingDate = $endingDate->setTimezone($timezone);
        }

        $possibleDateResults[$this->formatPossibleAggregateResultDate(
            $nextDate, $unit, $twelveHourTime
        )] = 0;

        while ($nextDate->lt($endingDate)) {
            if ($unit === self::BY_MONTHS) {
                $nextDate = $nextDate->addMonths(1);
            } elseif ($unit === self::BY_WEEKS) {
                $nextDate = $nextDate->addWeeks(1);
            } elseif ($unit === self::BY_DAYS) {
                $nextDate = $nextDate->addDays(1);
            } elseif ($unit === self::BY_HOURS) {
                $nextDate = $nextDate->addHours(1);
            } elseif ($unit === self::BY_MINUTES) {
                $nextDate = $nextDate->addMinutes(1);
            }

            if ($nextDate->lte($endingDate)) {
                $possibleDateResults[
                    $this->formatPossibleAggregateResultDate(
                        $nextDate, $unit, $twelveHourTime
                    )
                ] = 0;
            }
        }

        return $possibleDateResults;
    }

    /**
     * Format the possible aggregate result date into a proper string.
     *
     * @param  \Cake\Chronos\Chronos  $date
     * @param  string  $unit
     * @param  bool  $twelveHourTime
     * @return string
     */
    protected function formatPossibleAggregateResultDate(Chronos $date, $unit, $twelveHourTime)
    {
        switch ($unit) {
            case 'month':
                return __($date->format('F')).' '.$date->format('Y');

            case 'week':
                return __($date->startOfWeek()->format('F')).' '.$date->startOfWeek()->format('j').' - '.
                       __($date->endOfWeek()->format('F')).' '.$date->endOfWeek()->format('j');

            case 'day':
                return __($date->format('F')).' '.$date->format('j').', '.$date->format('Y');

            case 'hour':
                return $twelveHourTime
                        ? __($date->format('F')).' '.$date->format('j').' - '.$date->format('g:00 A')
                        : __($date->format('F')).' '.$date->format('j').' - '.$date->format('G:00');

            case 'minute':
                return $twelveHourTime
                        ? __($date->format('F')).' '.$date->format('j').' - '.$date->format('g:i A')
                        : __($date->format('F')).' '.$date->format('j').' - '.$date->format('G:i');
        }
    }

    /**
     * Get default timezone.
     *
     * @return mixed
     */
    private function getDefaultTimezone()
    {
        return request()->timezone;
    }
}
