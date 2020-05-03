<?php

namespace Laravel\Nova\Fields;

trait HasPreview
{
    /**
     * The callback used to retrieve the preview URL.
     *
     * @var callable
     */
    public $previewUrlCallback;

    /**
     * The callback used to retrieve the thumbnail URL.
     *
     * @var callable
     */
    public $thumbnailUrlCallback;

    /**
     * Specify the callback that should be used to retrieve the preview URL.
     *
     * @param  callable  $previewUrlCallback
     * @return $this
     */
    public function preview(callable $previewUrlCallback)
    {
        $this->previewUrlCallback = $previewUrlCallback;

        return $this;
    }

    /**
     * Resolve the preview URL for the field.
     *
     * @return string|null
     */
    public function resolvePreviewUrl()
    {
        return call_user_func($this->previewUrlCallback, $this->value, $this->getStorageDisk(), $this->resource);
    }
}
