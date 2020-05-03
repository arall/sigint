<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Database\Eloquent\Model;

class Tag extends Model
{
    /**
     * Get all of the posts with this tag.
     */
    public function posts()
    {
        return $this->morphedByMany(Post::class, 'taggable')->withPivot('admin');
    }
}
