<?php

namespace Laravel\Nova\Macros;

use Illuminate\Support\Carbon;

class FirstDayOfQuarter
{
    /**
     * Execute the macro.
     *
     * @param  string  $timezone
     *
     * @return \DateTimeInterface
     */
    public function firstDayOfQuarter()
    {
        return function ($timezone = 'UTC') {
            [$year, $month] = [now($timezone)->year, now($timezone)->month];

            if (in_array($month, [1, 2, 3])) {
                return Carbon::create($year, 1, 1)->setTimezone($timezone)->setTime(0, 0);
            } elseif (in_array($month, [4, 5, 6])) {
                return Carbon::create($year, 4, 1)->setTimezone($timezone)->setTime(0, 0);
            } elseif (in_array($month, [7, 8, 9])) {
                return Carbon::create($year, 7, 1)->setTimezone($timezone)->setTime(0, 0);
            } elseif (in_array($month, [10, 11, 12])) {
                return Carbon::create($year, 10, 1)->setTimezone($timezone)->setTime(0, 0);
            }
        };
    }
}
