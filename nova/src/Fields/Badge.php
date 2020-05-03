<?php

namespace Laravel\Nova\Fields;

use Exception;

class Badge extends Field
{
    /**
     * Create a new field.
     *
     * @param  string  $name
     * @param  string|callable|null  $attribute
     * @param  callable|null  $resolveCallback
     * @return void
     */
    public function __construct($name, $attribute = null, callable $resolveCallback = null)
    {
        parent::__construct($name, $attribute, $resolveCallback);

        $this->exceptOnForms();
    }

    /**
     * The text alignment for the field's text in tables.
     *
     * @var string
     */
    public $textAlign = 'center';

    /**
     * The field's component.
     *
     * @var string
     */
    public $component = 'badge-field';

    /**
     * The labels that should be applied to the field's possible values.
     *
     * @var array
     */
    public $labels;

    /**
     * The callback used to determine the field's label.
     *
     * @var callable
     */
    public $labelCallback;

    /**
     * The mapping used for matching custom values to in-built badge types.
     *
     * @var array
     */
    public $map;

    /**
     * The built-in badge types and their corresponding CSS classes.
     *
     * @var array
     */
    public $types = [
        'success' => 'bg-success-light text-success-dark',
        'info' => 'bg-info-light text-info-dark',
        'danger' => 'bg-danger-light text-danger-dark',
        'warning' => 'bg-warning-light text-warning-dark',
    ];

    /**
     * Add badge types and their corresponding CSS classes to the built-in ones.
     *
     * @param  array  $types
     * @return $this
     */
    public function addTypes(array $types)
    {
        $this->types = array_merge($this->types, $types);

        return $this;
    }

    /**
     * Set the badge types and their corresponding CSS classes.
     *
     * @param  array  $types
     * @return $this
     */
    public function types(array $types)
    {
        $this->types = $types;

        return $this;
    }

    /**
     * Set the labels for each possible field value.
     *
     * @param  array  $labels
     * @return $this
     */
    public function labels(array $labels)
    {
        $this->labels = $labels;

        return $this;
    }

    /**
     * Set the callback to be used to determine the field's displayable label.
     *
     * @param  callable  $labelCallback
     * @return $this
     */
    public function label(callable $labelCallback)
    {
        $this->labelCallback = $labelCallback;

        return $this;
    }

    /**
     * Map the possible field values to the built-in badge types.
     *
     * @param  array  $map
     * @return $this
     */
    public function map(array $map)
    {
        $this->map = $map;

        return $this;
    }

    /**
     * Resolve the Badge's CSS classes based on the field's value.
     *
     * @return string
     */
    public function resolveBadgeClasses()
    {
        try {
            $mappedValue = $this->map[$this->value] ?? $this->value;

            return $this->types[$mappedValue];
        } catch (Exception $e) {
            throw new Exception("Error trying to find type [{$mappedValue}] inside of the field's type mapping.");
        }
    }

    /**
     * Resolve the display label for the Badge.
     *
     * @return string
     */
    public function resolveLabel()
    {
        if (isset($this->labelCallback)) {
            return call_user_func($this->labelCallback, $this->value);
        }

        return $this->labels[$this->value] ?? $this->value;
    }

    /**
     * Prepare the element for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'label' => $this->resolveLabel(),
            'typeClass' => $this->resolveBadgeClasses(),
        ]);
    }
}
