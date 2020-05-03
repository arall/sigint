<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Http\Request;
use Illuminate\Support\Fluent;
use Laravel\Nova\Tests\Fixtures\RelationshipGuesserResource;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceRelationshipGuesserTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_resource_can_be_guessed()
    {
        $fields = (new RelationshipGuesserResource(new Fluent))->fields(Request::create('/'));
        $this->assertEquals(UserResource::class, $fields[1]->resourceClass);
    }
}
