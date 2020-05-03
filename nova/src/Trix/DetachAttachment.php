<?php

namespace Laravel\Nova\Trix;

use Illuminate\Http\Request;

class DetachAttachment
{
    /**
     * Delete an attachment from the field.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return void
     */
    public function __invoke(Request $request)
    {
        Attachment::where('url', $request->attachmentUrl)
                        ->get()
                        ->each
                        ->purge();
    }
}
