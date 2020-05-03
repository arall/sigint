<?php

namespace Laravel\Nova\Fields;

trait Expandable
{
    /**
     * The callback to be used to determine whether the field should be expanded.
     *
     * @var \Closure
     */
    public $expandableCallback;

    /**
     * Whether to always show the content for the field expanded or not.
     *
     * @var bool
     */
    public $alwaysShow = false;

    /**
     * Always show the content of textarea fields inside Nova.
     *
     * @return $this
     */
    public function alwaysShow()
    {
        $this->alwaysShow = true;

        return $this;
    }

    /**
     * Define the callback that should be used to determine whether the field should be collapsed.
     *
     * @param  callable
     * @return $this
     */
    public function shouldShow(callable $expandableCallback)
    {
        $this->expandableCallback = $expandableCallback;

        return $this;
    }

    /**
     * Determine whether the field should be expanded.
     *
     * @return bool
     */
    public function shouldBeExpanded()
    {
        if ($this->alwaysShow) {
            return true;
        }

        return isset($this->expandableCallback)
                        ? call_user_func($this->expandableCallback)
                        : false;
    }
}
