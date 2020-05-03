<?php

namespace Laravel\Nova;

class TrashedStatus
{
    const DEFAULT = '';
    const WITH = 'with';
    const ONLY = 'only';

    public static function fromBoolean($withTrashed)
    {
        return $withTrashed ? self::WITH : self::DEFAULT;
    }
}
