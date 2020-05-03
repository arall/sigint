<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\IdFilter;
use Laravel\Nova\Tests\Fixtures\Role;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceCountTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_count_a_resource()
    {
        factory(User::class)->create();
        factory(User::class)->create();
        factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/count');

        $response->assertStatus(200);
        $this->assertEquals(3, $response->original['count']);
    }

    public function test_can_count_a_resource_via_search()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user3 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/count?search='.$user->email);

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['count']);
    }

    public function test_can_count_a_resource_via_filter()
    {
        factory(User::class)->create();
        factory(User::class)->create();
        factory(User::class)->create();

        $filters = base64_encode(json_encode([
            [
                'class' => IdFilter::class,
                'value' => 2,
            ],
        ]));

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/count?filters='.$filters);

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['count']);
    }

    public function test_can_count_a_resource_with_grouping()
    {
        $roles = factory(Role::class, 2)->create();

        factory(User::class, 3)
           ->create()
           ->each(function ($user) use ($roles) {
               $user->roles()->sync($roles);
           });

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/grouped-users/count');

        $response->assertStatus(200);
        $this->assertEquals(3, $response->original['count']);
    }
}
