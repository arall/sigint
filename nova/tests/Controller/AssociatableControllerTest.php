<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;

class AssociatableControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_retrieve_associatable_resources()
    {
        $user = factory(User::class, 2)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/associatable/user');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertTrue($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_can_retrieve_associatable_resources_via_search()
    {
        UserResource::$search = ['id'];

        $user = factory(User::class, 2)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/associatable/user?search=2');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertTrue($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);

        UserResource::$search = ['id', 'name', 'email'];
    }

    public function test_only_the_first_matching_record_may_be_retrieved()
    {
        $user = factory(User::class, 2)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/associatable/user?current=2&first=true');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertTrue($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_soft_deleted_records_are_excluded_by_default()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user2->delete();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/associatable/user');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
        ], $response->original['resources']->all());

        $this->assertCount(1, $response->original['resources']->all());
    }

    public function test_soft_deleted_records_may_be_included()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user2->delete();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/associatable/user?withTrashed=true');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertCount(2, $response->original['resources']->all());
    }
}
