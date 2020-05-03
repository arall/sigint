<?php

namespace Laravel\Nova\Fields;

trait Searchable
{
    /**
     * Indicates if this relationship is searchable.
     *
     * @var bool
     */
    public $searchable = false;

    /**
     * Indicates if the subtitle will be shown within search results.
     *
     * @var bool
     */
    public $withSubtitles = false;

    /**
     * Specify if the relationship should be searchable.
     *
     * @return $this
     */
    public function searchable()
    {
        $this->searchable = true;

        return $this;
    }

    /**
     * Enable subtitles within the related search results.
     *
     * @return $this
     */
    public function withSubtitles()
    {
        $this->withSubtitles = true;

        return $this;
    }
}
