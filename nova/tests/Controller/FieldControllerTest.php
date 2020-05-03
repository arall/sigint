<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\Role;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserPolicy;
use Laravel\Nova\Tests\IntegrationTest;

class FieldControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_retrieve_a_single_field()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/field/email');

        $response->assertStatus(200);
        $this->assertInstanceOf(Text::class, $response->original);
        $this->assertEquals('email', $response->original->attribute);
    }

    public function test_404_returned_if_field_doesnt_exist()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/field/missing-field');

        $response->assertStatus(404);
    }

    public function test_can_return_creation_fields()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/creation-fields');

        $fields = collect($response->original['fields']);

        $response->assertStatus(200);
        $this->assertCount(0, $fields->where('attribute', 'id'));
        $this->assertCount(1, $fields->where('attribute', 'name'));
        $this->assertCount(1, $fields->where('attribute', 'email'));
        $this->assertCount(1, $fields->where('attribute', 'form'));
        $this->assertCount(0, $fields->where('attribute', 'update'));
        $this->assertCount(0, $fields->where('attribute', 'posts'));
    }

    public function test_cant_retrieve_creation_fields_if_not_authorized_to_create_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.creatable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/creation-fields');

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.creatable']);

        $response->assertStatus(403);
    }

    public function test_can_return_update_fields()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/'.$user->id.'/update-fields')
                        ->assertOk();

        $fields = collect($response->original['fields']);
        $this->assertCount(0, $fields->where('attribute', 'id'));
        $this->assertCount(1, $fields->where('attribute', 'name'));
        $this->assertCount(1, $fields->where('attribute', 'email'));
        $this->assertCount(1, $fields->where('attribute', 'form'));
        $this->assertCount(1, $fields->where('attribute', 'update'));
        $this->assertCount(0, $fields->where('attribute', 'posts'));
    }

    public function test_creation_fields_do_not_contain_default_values()
    {
        $post = factory(Post::class)->create();
        $post->forceFill(['slug' => null]);
        $post->save();

        $response = $this->withExceptionHandling()
            ->getJson('/nova-api/posts/'.$post->id.'/update-fields');

        $response->assertJsonCount(3, 'fields');

        $this->assertNotEquals('default-slug', $response->decodeResponseJson()['fields'][3]['value']);
        $this->assertNull($response->decodeResponseJson()['fields'][3]['value']);
    }

    public function test_cant_retrieve_update_fields_if_not_authorized_to_update_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.updatable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/'.$user->id.'/update-fields');

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.updatable']);

        $response->assertStatus(403);
    }

    public function test_can_return_creation_pivot_fields()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/creation-pivot-fields/roles');

        $fields = collect($response->original);

        $response->assertStatus(200);
        $this->assertCount(1, $fields->where('attribute', 'admin'));
        $this->assertCount(0, $fields->where('attribute', 'pivot-update'));
    }

    public function test_can_return_creation_pivot_fields_with_parent_belongs_to()
    {
        $response = $this->withoutExceptionHandling()
            ->get('/nova-api/roles/creation-pivot-fields/users?editing=true&editMode=attach');

        $fields = collect($response->original);

        $response->assertStatus(200);
        $this->assertCount(1, $fields->where('attribute', 'admin'));
        $this->assertCount(0, $fields->where('attribute', 'pivot-update'));
    }

    public function test_can_return_update_pivot_fields()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();
        $user->roles()->attach($role);

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/'.$user->id.'/update-pivot-fields/roles/'.$role->id.'?viaRelationship=roles');

        $fields = collect($response->original);

        $response->assertStatus(200);
        $this->assertCount(1, $fields->where('attribute', 'pivot-update'));
    }

    public function test_can_return_viewable_property_authorized()
    {
        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();
        $post = factory(Post::class)->create(['user_id' => $user->id]);

        $response = $this->withExceptionHandling()
            ->get("/nova-api/posts/{$post->id}");

        $response->assertStatus(200);

        $fields = collect(json_decode(json_encode($response->original['resource']['fields']), true));

        $this->assertTrue($fields->firstWhere('attribute', 'user')['viewable']);
    }

    public function test_can_return_viewable_property_denied()
    {
        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();
        $post = factory(Post::class)->create(['user_id' => $user->id]);

        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.viewable'] = false;

        $response = $this->withExceptionHandling()
            ->get("/nova-api/posts/{$post->id}");

        $response->assertStatus(200);

        $fields = collect(json_decode(json_encode($response->original['resource']['fields']), true));

        unset($_SERVER['nova.user.viewable'], $_SERVER['nova.user.authorizable']);

        $this->assertFalse($fields->firstWhere('attribute', 'user')['viewable']);
    }

    public function test_can_return_viewable_property_hidden()
    {
        $user = factory(User::class)->create();
        $post = factory(Post::class)->create(['user_id' => $user->id]);

        $_SERVER['nova.user.viewable-field'] = false;

        $response = $this->withExceptionHandling()
            ->get("/nova-api/posts/{$post->id}");

        $response->assertStatus(200);

        $fields = collect(json_decode(json_encode($response->original['resource']['fields']), true));

        unset($_SERVER['nova.user.viewable-field']);

        $this->assertFalse($fields->firstWhere('attribute', 'user')['viewable']);
    }
}
