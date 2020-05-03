<?php

namespace Laravel\Nova\Fields;

trait PresentsImages
{
    /**
     * The maximum width of the component.
     *
     * @var int
     */
    public $maxWidth = 320;

    /**
     * Indicates whether the image should be fully rounded or not.
     *
     * @var bool
     */
    public $rounded = false;

    /**
     * Set the maximum width of the component.
     *
     * @param  int  $maxWidth
     * @return $this
     */
    public function maxWidth($maxWidth)
    {
        $this->maxWidth = $maxWidth;

        return $this;
    }

    /**
     * Display the image thumbnail with full-rounded edges.
     *
     * @return $this
     */
    public function rounded()
    {
        $this->rounded = true;

        return $this;
    }

    /**
     * Display the image thumbnail with square edges.
     *
     * @return $this
     */
    public function squared()
    {
        $this->rounded = false;

        return $this;
    }

    /**
     * Determine whether the field should have rounded corners.
     *
     * @return bool
     */
    public function isRounded()
    {
        return $this->rounded == true;
    }

    /**
     * Determine whether the field should have squared corners.
     *
     * @return bool
     */
    public function isSquared()
    {
        return $this->rounded == false;
    }

    /**
     * Return the attributes to present the image with.
     *
     * @return array
     */
    public function imageAttributes()
    {
        return [
            'maxWidth' => $this->maxWidth,
            'rounded' => $this->isRounded(),
        ];
    }
}
