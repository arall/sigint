<?php

namespace Laravel\Nova\Exceptions;

use Exception;

class MissingActionHandlerException extends Exception
{
    /**
     * Create a new exception instance.
     *
     * @param  mixed  $action
     * @param  string  $method
     * @return static
     */
    public static function make($action, $method)
    {
        return new static('Action handler ['.get_class($action).'@'.$method.'] not defined.');
    }
}
