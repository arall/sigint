<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Actions\ActionEvent;
use Laravel\Nova\ResourceToolElement;
use Laravel\Nova\Tests\Fixtures\Boolean;
use Laravel\Nova\Tests\Fixtures\DeniedActionPolicy;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\Role;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserPolicy;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceShowTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function tearDown(): void
    {
        parent::tearDown();

        $_SERVER['nova.authorize.forbidden-users'] = false;
        $_SERVER['nova.authorize.roles'] = true;
    }

    public function test_can_show_resource()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/1');

        $response->assertStatus(200);

        $this->assertEquals($user->id, $response->original['resource']['id']->value);
        $this->assertEquals('Primary', $response->original['resource']['id']->panel);
        $this->assertTrue($response->original['resource']['authorizedToUpdate']);
        $this->assertTrue($response->original['resource']['authorizedToDelete']);
        $this->assertTrue($response->original['resource']['softDeletes']);

        $this->assertEquals('User Resource Details', $response->original['panels'][0]->name);
    }

    public function test_can_show_resource_with_null_relation()
    {
        $post = factory(Post::class)->create([
            'user_id' => null,
        ]);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/posts/1');

        $response->assertStatus(200);

        $this->assertNull($post->user_id);
        $this->assertNull($response->original['resource']['fields'][0]->value);
    }

    public function test_authorization_information_is_correctly_adjusted_when_unauthorized()
    {
        $user = factory(User::class)->create();

        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.updatable'] = false;
        $_SERVER['nova.user.deletable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/1');

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.updatable']);
        unset($_SERVER['nova.user.deletable']);

        $response->assertStatus(200);

        $this->assertEquals($user->id, $response->original['resource']['id']->value);
        $this->assertFalse($response->original['resource']['authorizedToUpdate']);
        $this->assertFalse($response->original['resource']['authorizedToDelete']);
    }

    public function test_throws_404_when_trying_to_show_resource_that_doesnt_exist()
    {
        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/1');

        $response->assertStatus(404);
    }

    public function test_cant_show_resource_if_not_authorized_to_view_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.viewable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/1');

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.viewable']);

        $response->assertStatus(403);
    }

    public function test_forbidden_resources_are_not_shown_as_relationships()
    {
        // Verify Missing...
        $_SERVER['nova.authorize.roles'] = false;

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/'.$user->id);

        $fields = $response->original['resource']['fields'];
        $this->assertNull(collect($fields)->where('attribute', 'roles')->first());

        // Verify Present...
        $_SERVER['nova.authorize.roles'] = true;

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/users/'.$user->id);

        $fields = $response->original['resource']['fields'];
        $this->assertNotNull(collect($fields)->where('attribute', 'roles')->first());
    }

    public function test_field_panels_are_returned_correctly_and_fields_are_correctly_assigned()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/panels/1');

        $response->assertStatus(200);

        $fields = $response->original['resource']['fields'];

        // Default panel assignment...
        $this->assertEquals('Panel Resource Details', collect($fields)->where('attribute', 'email')->first()->panel);

        // Includes / Excludes...
        $this->assertNotNull(collect($fields)->where('attribute', 'include')->first());
        $this->assertEquals('Extra', collect($fields)->where('attribute', 'include')->first()->panel);
        $this->assertNull(collect($fields)->where('attribute', 'exclude')->first());

        $panels = $response->original['panels'];

        $this->assertEquals(3, count($panels));
        $this->assertEquals('Panel Resource Details', $panels[0]->name);
        $this->assertEquals('Basics', $panels[1]->name);
        $this->assertEquals('Extra', $panels[2]->name);
    }

    public function test_resource_with_no_panels_still_gets_default_panel()
    {
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/roles/1');

        $response->assertStatus(200);

        $fields = $response->original['resource']['fields'];

        $this->assertEquals('Role Resource Details', collect($fields)->where('attribute', 'id')->first()->panel);

        $panels = $response->original['panels'];
        $this->assertEquals(1, count($panels));
        $this->assertEquals('Role Resource Details', $panels[0]->name);
    }

    public function test_resource_tool_component_name()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
            ->getJson('/nova-api/users/'.$user->id);

        $response->assertStatus(200);

        $fields = $response->original['resource']['fields'];
        $filed = collect($fields)->whereInstanceOf(ResourceToolElement::class)->firstWhere('panel', 'My Resource Tool');

        $this->assertNotEmpty($filed);
        $this->assertEquals('my-resource-tool', $filed->component);

        $panels = $response->original['panels'];
        $panel = collect($panels)->firstWhere('name', 'My Resource Tool');

        $this->assertNotEmpty($panel);
        $this->assertEquals('panel', $panel->component);
    }

    public function test_actions_field_is_added()
    {
        $boolean = Boolean::create();

        $response = $this->withExceptionHandling()
                         ->getJson('/nova-api/booleans/'.$boolean->id);

        $response->assertStatus(200);

        $fields = $response->original['resource']['fields'];

        $this->assertCount(3, $fields);
    }

    public function test_actions_are_hidden_when_policy_forbids()
    {
        $boolean = Boolean::create();

        Gate::policy(ActionEvent::class, DeniedActionPolicy::class);

        $response = $this->withExceptionHandling()
            ->getJson('/nova-api/booleans/'.$boolean->id);

        $response->assertStatus(200);

        $fields = $response->original['resource']['fields'];

        $this->assertCount(2, $fields);
    }
}
