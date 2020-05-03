<?php

namespace Laravel\Nova\Fields;

use Laravel\Nova\Contracts\Cover;

class Avatar extends Image implements Cover
{
    /**
     * Create a new field.
     *
     * @param  string|null  $name
     * @param  string|null  $attribute
     * @param  string|null  $disk
     * @param  callable|null  $storageCallback
     * @return void
     */
    public function __construct($name = 'Avatar', $attribute = null, $disk = 'public', $storageCallback = null)
    {
        parent::__construct($name, $attribute, $disk, $storageCallback);

        $this->rounded();
    }
}
