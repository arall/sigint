<?php

namespace Laravel\Nova\Tests\Fixtures;

class PostWithCustomCreatedAt extends Post
{
    public const CREATED_AT = 'published_at';

    protected $table = 'posts';
}
