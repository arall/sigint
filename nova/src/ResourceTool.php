<?php

namespace Laravel\Nova;

use Closure;
use Illuminate\Support\Str;

class ResourceTool extends Panel
{
    use ProxiesCanSeeToGate;

    /**
     * The resource tool element.
     *
     * @var \Laravel\Nova\Element
     */
    public $element;

    /**
     * The resource tool's component.
     *
     * @var string
     */
    public $toolComponent;

    /**
     * Create a new resource tool instance.
     *
     * @return void
     */
    public function __construct()
    {
        parent::__construct($this->name(), [new ResourceToolElement($this->toolComponent())]);

        $this->element = $this->data[0];
    }

    /**
     * Create a new resource tool instance.
     *
     * @return static
     */
    public static function make(...$arguments)
    {
        return new static(...$arguments);
    }

    /**
     * Get the displayable name of the resource tool.
     *
     * @return string
     */
    public function name()
    {
        return $this->name ?: Str::title(Str::snake(class_basename(get_class($this)), ' '));
    }

    /**
     * Get the component name for the resource tool.
     *
     * @return string
     */
    public function toolComponent()
    {
        return $this->toolComponent ?? Str::kebab(class_basename(get_class($this)));
    }

    /**
     * Set the callback to be run to authorize viewing the card.
     *
     * @param  \Closure  $callback
     * @return $this
     */
    public function canSee(Closure $callback)
    {
        $this->element->canSee($callback);

        return $this;
    }

    /**
     * Set additional meta information for the resource tool.
     *
     * @param  array  $meta
     * @return $this
     */
    public function withMeta(array $meta)
    {
        $this->element->withMeta($meta);

        return $this;
    }

    /**
     * Dynamically proxy method calls to meta information.
     *
     * @param  string  $method
     * @param  array  $parameters
     * @return $this
     */
    public function __call($method, $parameters)
    {
        return $this->withMeta([$method => ($parameters[0] ?? true)]);
    }
}
