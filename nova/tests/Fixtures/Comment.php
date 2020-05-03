<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Comment extends Model
{
    /**
     * Get the commentable model.
     */
    public function commentable()
    {
        return $this->morphTo();
    }

    /**
     * Get the author of the comment.
     */
    public function author()
    {
        return $this->belongsTo(User::class, 'author_id');
    }
}
