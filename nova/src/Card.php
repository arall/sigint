<?php

namespace Laravel\Nova;

abstract class Card extends Element
{
    /**
     * The width of the card (1/3, 1/2, or full).
     *
     * @var string
     */
    public $width = '1/3';

    /**
     * Set the width of the card.
     *
     * @param  string  $width
     * @return $this
     */
    public function width($width)
    {
        $this->width = $width;

        return $this;
    }

    /**
     * Prepare the element for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge([
            'width' => $this->width,
        ], parent::jsonSerialize());
    }
}
