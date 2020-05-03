<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Database\Eloquent\Relations\Relation;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Actions\ActionEvent;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserPolicy;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceUpdateTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_update_resources()
    {
        $user = factory(User::class)->create([
            'name' => 'Taylor Otwell',
            'email' => 'taylor@laravel.com',
        ]);

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'David Hemphill',
                            'email' => 'david@laravel.com',
                            'password' => 'password',
                        ]);

        $response->assertStatus(200);

        $user = $user->fresh();
        $this->assertEquals('David Hemphill', $user->name);
        $this->assertEquals('david@laravel.com', $user->email);

        $this->assertCount(1, ActionEvent::all());

        $actionEvent = ActionEvent::first();

        $this->assertEquals('Update', $actionEvent->name);
        $this->assertEquals($user->id, $actionEvent->target->id);
        $this->assertSubset(['name' => 'Taylor Otwell', 'email' => 'taylor@laravel.com'], $actionEvent->original);
        $this->assertSubset(['name' => 'David Hemphill', 'email' => 'david@laravel.com'], $actionEvent->changes);
        $this->assertTrue($user->is(ActionEvent::first()->target));
    }

    public function test_cant_update_resource_fields_that_arent_authorized()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'Taylor Otwell',
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                            'restricted' => 'No',
                        ]);

        $response->assertStatus(200);

        $user = $user->fresh();
        $this->assertEquals('Taylor Otwell', $user->name);
        $this->assertEquals('taylor@laravel.com', $user->email);
        $this->assertEquals('Yes', $user->restricted);
    }

    public function test_cant_update_resources_that_have_been_edited_since_retrieval()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'Taylor Otwell',
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                            '_retrieved_at' => now()->subHours(1)->getTimestamp(),
                        ]);

        $response->assertStatus(409);
    }

    public function test_can_disable_traffic_cop()
    {
        $_SERVER['nova.user.trafficCop'] = false;

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'Taylor Otwell',
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                            '_retrieved_at' => now()->subHours(1)->getTimestamp(),
                        ]);

        $response->assertStatus(200);
    }

    public function test_must_be_authorized_to_update_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.updatable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'Taylor Otwell',
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                        ]);

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.updatable']);

        $response->assertStatus(403);
    }

    public function test_must_be_authorized_to_relate_related_resource_to_update_a_resource_that_it_belongs_to()
    {
        $post = factory(Post::class)->create();

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user3 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => $user3->id,
                            'title' => 'Fake Title',
                            'slug' => 'fake-title',
                        ]);

        $response->assertStatus(422);
    }

    public function test_parent_resource_policy_may_prevent_adding_related_resources()
    {
        $post = factory(Post::class)->create();
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => $user->id,
                            'title' => 'Fake Title',
                            'slug' => 'fake-title',
                        ]);

        $response->assertStatus(200);

        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.addPost'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => $user->id,
                            'title' => 'Fake Title',
                            'slug' => 'fake-title',
                        ]);

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.addPost']);

        $response->assertStatus(422);
        $this->assertInstanceOf(User::class, $_SERVER['nova.user.addPostModel']);
        $this->assertEquals($user->id, $_SERVER['nova.user.addPostModel']->id);

        unset($_SERVER['nova.user.addPostModel']);
    }

    public function test_can_update_soft_deleted_resources()
    {
        $user = factory(User::class)->create();
        $user->delete();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => 'Taylor Otwell',
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                        ]);

        $response->assertStatus(200);

        $user = $user->fresh();
        $this->assertEquals('Taylor Otwell', $user->name);
        $this->assertEquals('taylor@laravel.com', $user->email);

        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals('Update', ActionEvent::first()->name);
        $this->assertEquals($user->id, ActionEvent::first()->target->id);
        $this->assertTrue($user->is(ActionEvent::first()->target));
    }

    public function test_user_can_maintain_same_email_without_unique_errors()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => $user->name,
                            'email' => $user->email,
                            'password' => $user->password,
                        ]);

        $response->assertStatus(200);
    }

    public function test_validation_rules_are_applied()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/users/'.$user->id, [
                            'name' => $user->name,
                            'email' => $user2->email,
                            'password' => $user->password,
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors([
            'email',
        ]);
    }

    public function test_resource_with_parent_can_be_updated()
    {
        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => $post->user->id,
                            'title' => 'Fake Title',
                            'slug' => 'fake-title',
                        ]);

        $response->assertStatus(200);
    }

    public function test_parent_resource_must_exist()
    {
        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => 100,
                            'title' => 'Fake Title',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['user']);
    }

    public function test_action_event_should_honor_custom_polymorphic_type_for_resource_update()
    {
        Relation::morphMap(['post' => Post::class]);

        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/posts/'.$post->id, [
                            'user' => $post->user_id,
                            'title' => 'Fake Title',
                            'slug' => 'fake-title',
                        ]);

        $actionEvent = ActionEvent::first();

        $this->assertEquals('Update', $actionEvent->name);

        $this->assertEquals('post', $actionEvent->actionable_type);
        $this->assertEquals($post->id, $actionEvent->actionable_id);

        $this->assertEquals('post', $actionEvent->target_type);
        $this->assertEquals($post->id, $actionEvent->target_id);

        $this->assertEquals('post', $actionEvent->model_type);
        $this->assertEquals($post->id, $actionEvent->model_id);

        Relation::morphMap([], false);
    }

    public function test_fields_are_not_validated_if_user_cant_see_them()
    {
        $_SERVER['weight-field.canSee'] = false;
        $_SERVER['weight-field.readonly'] = false;

        $user = factory(User::class)->create(['weight' => 250]);

        $this->withExceptionHandling()
            ->putJson('/nova-api/users/'.$user->id, [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                // 'weight' => 190,
                'password' => 'password',
            ])
            ->assertOk();
    }

    public function test_fields_are_not_updated_if_user_cant_see_them()
    {
        $_SERVER['weight-field.canSee'] = false;
        $_SERVER['weight-field.readonly'] = false;

        $user = factory(User::class)->create(['weight' => 250]);

        $this->withExceptionHandling()
            ->putJson('/nova-api/users/'.$user->id, [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                'weight' => 190,
                'password' => 'password',
            ])
            ->assertOk();

        $this->assertEquals(250, $user->fresh()->weight);
    }

    public function test_readonly_fields_are_not_validated()
    {
        $_SERVER['weight-field.canSee'] = true;
        $_SERVER['weight-field.readonly'] = true;

        $user = factory(User::class)->create(['weight' => 250]);

        $this->withExceptionHandling()
            ->putJson(sprintf('/nova-api/users/%s?editing=true&editMode=update', $user->id), [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                // 'weight' => 190,
                'password' => 'password',
            ])
            ->assertOk();
    }

    public function test_readonly_fields_are_not_updated()
    {
        $_SERVER['weight-field.canSee'] = true;
        $_SERVER['weight-field.readonly'] = true;

        $user = factory(User::class)->create(['weight' => 250]);

        $this->withoutExceptionHandling()
            ->putJson(sprintf('/nova-api/users/%s?editing=true&editMode=update', $user->id), [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                'weight' => 190,
                'password' => 'password',
            ])
            ->assertOk();

        $this->assertEquals(250, $user->fresh()->weight);
    }

    public function test_resource_can_redirect_to_default_uri_on_update()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
            ->putJson('/nova-api/users/'.$user->id, [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                'password' => 'password',
            ]);

        $response->assertJson(['redirect' => '/resources/users/1']);
    }

    public function test_resource_can_redirect_to_custom_uri_on_update()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
            ->putJson('/nova-api/users-with-redirects/'.$user->id, [
                'name' => 'Taylor Otwell',
                'email' => 'taylor@laravel.com',
                'password' => 'password',
            ]);

        $response->assertJson(['redirect' => 'https://google.com']);
    }

    public function test_select_resource_query_count_on_update()
    {
        $user = factory(User::class)->create(['weight' => 250]);

        DB::enableQueryLog();

        $this->withExceptionHandling()
             ->putJson('/nova-api/users/'.$user->id, [
                 'name' => 'Taylor Otwell',
                 'email' => 'taylor@laravel.com',
                 'password' => 'password',
             ])
             ->assertOk();

        DB::disableQueryLog();

        $queries = count(array_filter(DB::getQueryLog(), function ($log) {
            return $log['query'] === 'select * from "users" where "users"."id" = ? limit 1';
        }));

        $this->assertEquals(1, $queries);
    }

    public function test_uses_existing_resource_on_retrieving_validation_rules_from_callbacks()
    {
        $user = factory(User::class)->create(['email' => 'taylor@laravel.com']);

        $_SERVER['nova.user.fixedValuesOnUpdate'] = true;

        $this->withExceptionHandling()
             ->putJson('/nova-api/users/'.$user->id, [
                 'name' => 'Taylor Otwell', // The name is required to be 'Taylor Otwell'
                 'email' => 'taylor@laravel.com',
                 'password' => 'incorrectpassword', // The password is required to be 'taylorotwell'
             ])
             ->assertStatus(422);

        $this->withExceptionHandling()
             ->putJson('/nova-api/users/'.$user->id, [
                 'name' => 'David Hemphill', // The name is required to be 'Taylor Otwell'
                 'email' => 'taylor@laravel.com',
                 'password' => 'taylorotwell', // The password is required to be 'taylorotwell'
             ])
             ->assertStatus(422);

        $this->withExceptionHandling()
             ->putJson('/nova-api/users/'.$user->id, [
                 'name' => 'Taylor Otwell', // The name is required to be 'Taylor Otwell'
                 'email' => 'taylor@laravel.com',
                 'password' => 'taylorotwell', // The password is required to be 'taylorotwell'
             ])
             ->assertOk();

        unset($_SERVER['nova.user.fixedValuesOnUpdate']);

        $this->assertEquals('taylorotwell', $user->fresh()->password);
    }

    public function test_should_store_action_event_on_correct_connection_when_updating()
    {
        $this->setupActionEventsOnSeparateConnection();

        $user = factory(User::class)->create([
            'name' => 'Taylor Otwell',
            'email' => 'taylor@laravel.com',
        ]);

        $response = $this->withExceptionHandling()
            ->putJson('/nova-api/users/'.$user->id, [
                'name' => 'David Hemphill',
                'email' => 'david@laravel.com',
                'password' => 'password',
            ]);

        $response->assertStatus(200);

        $this->assertCount(0, DB::connection('sqlite')->table('action_events')->get());
        $this->assertCount(1, DB::connection('sqlite-custom')->table('action_events')->get());

        tap(Nova::actionEvent()->first(), function ($actionEvent) use ($user) {
            $this->assertEquals('Update', $actionEvent->name);
            $this->assertEquals($user->id, $actionEvent->target_id);
            $this->assertSubset(['name' => 'Taylor Otwell', 'email' => 'taylor@laravel.com'], $actionEvent->original);
            $this->assertSubset(['name' => 'David Hemphill', 'email' => 'david@laravel.com'], $actionEvent->changes);
        });
    }

    public function tearDown(): void
    {
        unset($_SERVER['weight-field.readonly']);
        unset($_SERVER['weight-field.canSee']);

        parent::tearDown();
    }
}
