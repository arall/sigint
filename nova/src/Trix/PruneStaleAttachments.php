<?php

namespace Laravel\Nova\Trix;

class PruneStaleAttachments
{
    /**
     * Prune the stale attachments from the system.
     *
     * @return void
     */
    public function __invoke()
    {
        PendingAttachment::where('created_at', '<=', now()->subDays(1))
                    ->orderBy('id', 'desc')
                    ->chunk(100, function ($attachments) {
                        $attachments->each->purge();
                    });
    }
}
