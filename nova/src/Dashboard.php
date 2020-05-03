<?php

namespace Laravel\Nova;

use Illuminate\Support\Str;

abstract class Dashboard extends Element
{
    use AuthorizedToSee,
        Metable,
        ProxiesCanSeeToGate;

    /**
     * Get the displayable name of the dashboard.
     *
     * @return string
     */
    public static function label()
    {
        return Str::singular(class_basename(get_called_class()));
    }

    /**
     * Get the URI key of the dashboard.
     *
     * @return string
     */
    public static function uriKey()
    {
        return Str::singular(Str::snake(class_basename(get_called_class()), '-'));
    }
}
