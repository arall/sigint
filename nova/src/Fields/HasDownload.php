<?php

namespace Laravel\Nova\Fields;

use Laravel\Nova\Http\Requests\NovaRequest;

trait HasDownload
{
    /**
     * The callback used to generate the download HTTP response.
     *
     * @var callable
     */
    public $downloadResponseCallback;

    /**
     * Determin if the file is able to be downloaded.
     *
     * @var bool
     */
    public $downloadsAreEnabled = true;

    /**
     * Disable downloading the file.
     *
     * @return $this
     */
    public function disableDownload()
    {
        $this->downloadsAreEnabled = false;

        return $this;
    }

    /**
     * Specify the callback that should be used to create a download HTTP response.
     *
     * @param  callable  $downloadResponseCallback
     * @return $this
     */
    public function download(callable $downloadResponseCallback)
    {
        $this->downloadResponseCallback = $downloadResponseCallback;

        return $this;
    }

    /**
     * Create an HTTP response to download the underlying field.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Laravel\Nova\Resource  $resource
     * @return \Illuminate\Http\Response
     */
    public function toDownloadResponse(NovaRequest $request, $resource)
    {
        return call_user_func(
            $this->downloadResponseCallback, $request, $resource->resource
        );
    }
}
