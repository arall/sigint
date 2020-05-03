<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Tests\Fixtures\Tag;
use Laravel\Nova\Tests\Fixtures\TagPolicy;
use Laravel\Nova\Tests\Fixtures\TagResource;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceAuthorizationTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_resource_is_automatically_authorizable_if_it_has_policy()
    {
        $this->assertFalse(TagResource::authorizable());

        Gate::policy(Tag::class, TagPolicy::class);

        $this->assertTrue(TagResource::authorizable());
    }
}
