<?php

namespace Laravel\Nova\Fields;

use Illuminate\Support\Collection;
use Illuminate\Support\Fluent;

class ResolvedFields extends Fluent
{
    /**
     * The post-storage callbacks for the fields.
     *
     * @var \Illuminate\Support\Collection
     */
    public $callbacks;

    /**
     * Create a new resolved fields instance.
     *
     * @param  \Illuminate\Support\Collection  $attributes
     * @param  \Illuminate\Support\Collection  $callbacks
     * @return void
     */
    public function __construct(Collection $attributes, Collection $callbacks)
    {
        parent::__construct($attributes->all());

        $this->callbacks = $callbacks;
    }

    /**
     * Get the post-storage callbacks for the fields.
     *
     * @return \Illuminate\Support\Collection
     */
    public function callbacks()
    {
        return $this->callbacks;
    }
}
