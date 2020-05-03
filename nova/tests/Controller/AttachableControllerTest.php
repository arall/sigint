<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\Role;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class AttachableControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_retrieve_attachable_resources()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/'.$user->id.'/attachable/roles');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_can_retrieve_attachable_resources_with_custom_relation_key()
    {
        $_SERVER['nova.useRolesCustomAttribute'] = true;

        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withoutExceptionHandling()
            ->getJson('/nova-api/users/'.$user->id.'/attachable/roles');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);

        unset($_SERVER['nova.useRolesCustomAttribute']);
    }

    public function test_can_retrieve_attachable_resources_by_search()
    {
        $user = factory(User::class)->create();

        $role = factory(Role::class)->create();
        $role2 = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/'.$user->id.'/attachable/roles?search='.$role2->name);

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_only_the_first_matching_record_may_be_retrieved()
    {
        $user = factory(User::class)->create();

        $role = factory(Role::class)->create();
        $role2 = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/'.$user->id.'/attachable/roles?current='.$role2->id.'&first=true');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_can_retrieve_attachable_resources_with_same_relation_model()
    {
        factory(User::class)->create();
        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
            ->getJson('/nova-api/posts/'.$post->id.'/attachable/users');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => 1],
            ['value' => 2, 'display' => 2],
        ], $response->original['resources']->all());
    }
}
