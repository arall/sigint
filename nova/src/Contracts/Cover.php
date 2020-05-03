<?php

namespace Laravel\Nova\Contracts;

interface Cover
{
    /**
     * Resolve the thumbnail URL for the field.
     *
     * @return string|null
     */
    public function resolveThumbnailUrl();
}
