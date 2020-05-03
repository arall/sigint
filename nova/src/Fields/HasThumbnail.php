<?php

namespace Laravel\Nova\Fields;

trait HasThumbnail
{
    /**
     * The callback used to retrieve the thumbnail URL.
     *
     * @var callable
     */
    public $thumbnailUrlCallback;

    /**
     * Specify the callback that should be used to retrieve the thumbnail URL.
     *
     * @param  callable  $thumbnailUrlCallback
     * @return $this
     */
    public function thumbnail(callable $thumbnailUrlCallback)
    {
        $this->thumbnailUrlCallback = $thumbnailUrlCallback;

        return $this;
    }

    /**
     * Resolve the thumbnail URL for the field.
     *
     * @return string|null
     */
    public function resolveThumbnailUrl()
    {
        return call_user_func($this->thumbnailUrlCallback, $this->value, $this->getStorageDisk(), $this->resource);
    }
}
