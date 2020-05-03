<?php

namespace Laravel\Nova\Fields;

trait AcceptsTypes
{
    /**
     * The file types accepted by the field.
     *
     * @var string
     */
    public $acceptedTypes;

    /**
     * Set the fields accepted file types.
     *
     * @param  string  $acceptedTypes
     * @return $this
     */
    public function acceptedTypes($acceptedTypes)
    {
        $this->acceptedTypes = $acceptedTypes;

        return $this;
    }
}
