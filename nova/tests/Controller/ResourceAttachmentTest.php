<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Actions\ActionEvent;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\Role;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserPolicy;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceAttachmentTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_attach_resources()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withoutExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => $role->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'roles',
                        ]);

        $response->assertStatus(200);

        $this->assertCount(1, $user->fresh()->roles);
        $this->assertEquals($role->id, $user->fresh()->roles->first()->id);
        $this->assertEquals('Y', $user->fresh()->roles->first()->pivot->admin);

        $this->assertCount(1, ActionEvent::all());

        $actionEvent = ActionEvent::first();
        $this->assertEquals('Attach', $actionEvent->name);
        $this->assertEquals('finished', $actionEvent->status);

        $this->assertEquals($user->id, $actionEvent->target->id);
        $this->assertEmpty($actionEvent->original);

        $this->assertSubset([
            'user_id' => $user->id,
            'role_id' => $role->id,
            'admin' => 'Y',
        ], $actionEvent->changes);
    }

    public function test_cant_set_pivot_fields_that_arent_authorized()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => $role->id,
                            'admin' => 'Y',
                            'restricted' => 'No',
                            'viaRelationship' => 'roles',
                        ]);

        $response->assertStatus(200);

        $this->assertEquals('Yes', $user->fresh()->roles->first()->pivot->restricted);
    }

    public function test_can_attach_soft_deleted_resources()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();
        $user->delete();

        $response = $this->withoutExceptionHandling()
                        ->postJson('/nova-api/roles/'.$role->id.'/attach/users', [
                            'users' => $user->id,
                            'users_trashed' => 'true',
                            'admin' => 'Y',
                            'viaRelationship' => 'users',
                        ]);

        $response->assertStatus(200);

        $users = $role->fresh()->users()->withTrashed()->get();

        $this->assertCount(1, $users);
        $this->assertEquals($user->id, $users->first()->id);
        $this->assertEquals('Y', $users->first()->pivot->admin);
    }

    public function test_attached_resource_must_exist()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => 100,
                            'admin' => 'Y',
                            'viaRelationship' => 'roles',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['roles']);

        $this->assertCount(0, $user->fresh()->roles);
    }

    public function test_cant_attach_resources_that_arent_relatable()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user3 = factory(User::class)->create();

        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/roles/'.$role->id.'/attach/users', [
                            'users' => $user3->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'users',
                        ]);

        $response->assertStatus(422);
    }

    // This behavior was changed...
    // public function test_cant_attach_resources_that_arent_relatable_at_all()
    // {
    //     $user = factory(User::class)->create();
    //     $role = factory(Role::class)->create();

    //     $_SERVER['nova.user.authorizable'] = true;
    //     $_SERVER['nova.user.attachAnyRole'] = false;

    //     Gate::policy(User::class, UserPolicy::class);

    //     $response = $this->withExceptionHandling()
    //                     ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
    //                         'roles' => $role->id,
    //                         'admin' => 'Y',
    //                         'viaRelationship' => 'roles',
    //                     ]);

    //     unset($_SERVER['nova.user.authorizable']);
    //     unset($_SERVER['nova.user.attachAnyRole']);

    //     $response->assertStatus(422);
    //     $this->assertInstanceOf(User::class, $_SERVER['nova.user.attachAnyRoleUser']);
    //     $this->assertEquals($user->id, $_SERVER['nova.user.attachAnyRoleUser']->id);

    //     unset($_SERVER['nova.user.attachAnyRoleUser']);
    // }

    public function test_cant_attach_things_to_resources_that_prevent_the_attachment_via_a_policy()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.attachRole'] = false;
        $_SERVER['nova.user.attachAnyRole'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => $role->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'roles',
                        ]);

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.attachRole']);
        unset($_SERVER['nova.user.attachAnyRole']);

        $response->assertStatus(422);
        $this->assertInstanceOf(User::class, $_SERVER['nova.user.attachRoleUser']);
        $this->assertInstanceOf(Role::class, $_SERVER['nova.user.attachRoleRole']);
        $this->assertEquals($user->id, $_SERVER['nova.user.attachRoleUser']->id);
        $this->assertEquals($role->id, $_SERVER['nova.user.attachRoleRole']->id);

        unset($_SERVER['nova.user.attachRoleUser']);
        unset($_SERVER['nova.user.attachRoleRole']);
    }

    public function test_attached_resource_must_not_already_be_attached()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();
        $user->roles()->attach($role);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => $role->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'roles',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['roles']);

        $this->assertCount(1, $user->fresh()->roles);
    }

    public function test_pivot_data_is_validated()
    {
        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                            'roles' => $role->id,
                            'viaRelationship' => 'roles',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['admin']);
    }

    public function test_can_attach_resources_with_custom_foreign_keys()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
            ->postJson('/nova-api/users/'.$user->id.'/attach/users', [
                'users' => $user2->id,
                'users_trashed' => false,
                'viaRelationship' => 'relatedUsers',
            ]);

        $response->assertStatus(200);

        $this->assertCount(1, $user->fresh()->relatedUsers);
        $this->assertEquals($user2->id, $user->fresh()->relatedUsers->first()->id);
    }

    public function test_attachable_resource_with_custom_relationship_name_are_validated()
    {
        $_SERVER['nova.useRolesCustomAttribute'] = true;

        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
            ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                'roles' => null,
                'roles_trashed' => false,
                'viaRelationship' => 'userRoles',
            ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors('roles');

        unset($_SERVER['nova.useRolesCustomAttribute']);
    }

    public function test_attach_resource_with_custom_relationship_name()
    {
        $_SERVER['nova.useRolesCustomAttribute'] = true;

        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withoutExceptionHandling()
            ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                'roles' => $role->id,
                'admin' => 'Y',
                'viaRelationship' => 'userRoles',
            ]);

        $response->assertOk();

        unset($_SERVER['nova.useRolesCustomAttribute']);
    }

    public function test_should_store_action_event_on_correct_connection_when_updating_attachments()
    {
        $this->setupActionEventsOnSeparateConnection();

        $user = factory(User::class)->create();
        $role = factory(Role::class)->create();

        $response = $this->withExceptionHandling()
            ->postJson('/nova-api/users/'.$user->id.'/attach/roles', [
                'roles' => $role->id,
                'admin' => 'Y',
                'viaRelationship' => 'roles',
            ]);

        $response->assertStatus(200);

        $this->assertCount(1, $user->fresh()->roles);
        $this->assertEquals($role->id, $user->fresh()->roles->first()->id);
        $this->assertEquals('Y', $user->fresh()->roles->first()->pivot->admin);

        $this->assertCount(0, DB::connection('sqlite')->table('action_events')->get());
        $this->assertCount(1, DB::connection('sqlite-custom')->table('action_events')->get());

        tap(Nova::actionEvent()->first(), function ($actionEvent) use ($user, $role) {
            $this->assertEquals('Attach', $actionEvent->name);
            $this->assertEquals('finished', $actionEvent->status);

            $this->assertEquals($user->id, $actionEvent->target_id);
            $this->assertEmpty($actionEvent->original);

            $this->assertSubset([
                'user_id' => $user->id,
                'role_id' => $role->id,
                'admin' => 'Y',
            ], $actionEvent->changes);
        });
    }
}
