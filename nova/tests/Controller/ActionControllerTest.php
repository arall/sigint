<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Database\Eloquent\Relations\Relation;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Actions\ActionEvent;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\Comment;
use Laravel\Nova\Tests\Fixtures\DestructiveAction;
use Laravel\Nova\Tests\Fixtures\EmptyAction;
use Laravel\Nova\Tests\Fixtures\ExceptionAction;
use Laravel\Nova\Tests\Fixtures\FailingAction;
use Laravel\Nova\Tests\Fixtures\HandleResultAction;
use Laravel\Nova\Tests\Fixtures\IdFilter;
use Laravel\Nova\Tests\Fixtures\NoopAction;
use Laravel\Nova\Tests\Fixtures\NoopActionWithoutActionable;
use Laravel\Nova\Tests\Fixtures\OpensInNewTabAction;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\QueuedAction;
use Laravel\Nova\Tests\Fixtures\QueuedResourceAction;
use Laravel\Nova\Tests\Fixtures\QueuedUpdateStatusAction;
use Laravel\Nova\Tests\Fixtures\RedirectAction;
use Laravel\Nova\Tests\Fixtures\RequiredFieldAction;
use Laravel\Nova\Tests\Fixtures\UnauthorizedAction;
use Laravel\Nova\Tests\Fixtures\UnrunnableAction;
use Laravel\Nova\Tests\Fixtures\UnrunnableDestructiveAction;
use Laravel\Nova\Tests\Fixtures\UpdateStatusAction;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserPolicy;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;

class ActionControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();

        Action::$chunkCount = 200;
    }

    public function tearDown(): void
    {
        unset($_SERVER['queuedAction.applied']);
        unset($_SERVER['queuedAction.appliedFields']);
        unset($_SERVER['queuedResourceAction.applied']);
        unset($_SERVER['queuedResourceAction.appliedFields']);

        parent::tearDown();
    }

    public function test_can_retrieve_actions_for_a_resource()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/actions');

        $response->assertStatus(200);
        $this->assertInstanceOf(Action::class, $response->original['actions'][0]);
    }

    public function test_actions_can_be_applied()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals(['message' => 'Hello World'], $response->original);

        $this->assertEquals($user2->id, NoopAction::$applied[0][0]->id);
        $this->assertEquals($user->id, NoopAction::$applied[0][1]->id);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
        $this->assertEquals('callback', NoopAction::$appliedFields[0]->callbacks()['callback']());

        $this->assertCount(2, ActionEvent::all());
        $actionEvent = ActionEvent::first();
        $this->assertEquals('Noop Action', $actionEvent->name);
        $this->assertEquals(['test' => 'Taylor Otwell'], unserialize($actionEvent->fields));
        $this->assertEquals('finished', $actionEvent->status);
    }

    public function test_actions_support_redirects()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new RedirectAction)->uriKey(), [
                            'resources' => implode(',', [$user->id]),
                        ]);

        $this->assertEquals(['redirect' => 'http://yahoo.com'], $response->original);
    }

    public function test_actions_support_opening_in_a_new_tab()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new OpensInNewTabAction)->uriKey(), [
                            'resources' => implode(',', [$user->id]),
                        ]);

        $this->assertEquals(['openInNewTab' => 'http://google.com'], $response->original);
    }

    public function test_action_fields_are_validated()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/users/action?action='.(new RequiredFieldAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => '',
                            'callback' => '',
                        ]);

        $response->assertStatus(422);
    }

    public function test_action_cant_be_applied_if_not_authorized_to_update_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.updatable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.updatable']);

        $response->assertStatus(200);
        $this->assertEmpty(NoopAction::$applied);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_destructive_action_cant_be_applied_if_not_authorized_to_delete_resource()
    {
        $_SERVER['nova.user.authorizable'] = true;
        $_SERVER['nova.user.updatable'] = true;
        $_SERVER['nova.user.deletable'] = false;

        Gate::policy(User::class, UserPolicy::class);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new DestructiveAction)->uriKey(), [
                            'resources' => $user->id,
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        unset($_SERVER['nova.user.authorizable']);
        unset($_SERVER['nova.user.updatable']);
        unset($_SERVER['nova.user.deletable']);

        $response->assertStatus(200);
        $this->assertEmpty(NoopAction::$applied);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_action_cant_be_applied_if_not_authorized_to_run_action()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new UnrunnableAction)->uriKey(), [
                            'resources' => $user->id,
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);
        $this->assertEmpty(UnrunnableAction::$applied);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_action_cant_be_applied_if_not_authorized_to_run_destructive_action()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new UnrunnableDestructiveAction)->uriKey(), [
                            'resources' => $user->id,
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);
        $this->assertEmpty(UnrunnableDestructiveAction::$applied);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_chunking_is_properly_applied()
    {
        Action::$chunkCount = 2;

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        $user3 = factory(User::class)->create();
        $user4 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id, $user3->id, $user4->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);

        $this->assertCount(4, ActionEvent::all());
        $this->assertCount(4, ActionEvent::where('status', 'finished')->get());
        $this->assertCount(2, DB::table('action_events')->distinct()->select('batch_id')->get());
    }

    public function test_actions_cant_be_run_if_they_are_not_authorized_to_see_the_action()
    {
        $user = factory(User::class)->create();

        $resource = new UserResource($user);

        $this->assertNotNull(collect($resource->actions(NovaRequest::create('/')))->first(function ($action) {
            return $action instanceof UnauthorizedAction;
        }));

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new UnauthorizedAction)->uriKey(), [
                            'resources' => implode(',', [$user->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(403);

        $this->assertCount(0, ActionEvent::all());
    }

    public function test_actions_can_be_applied_to_an_entire_resource()
    {
        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
    }

    public function test_actions_can_be_applied_to_an_entire_resource_with_relationship_constraint()
    {
        $comment = factory(Comment::class)->create();
        $comment2 = factory(Comment::class)->create();

        $post = factory(Post::class)->create();
        $post->comments()->save($comment);

        $post2 = factory(Post::class)->create();
        $post2->comments()->save($comment2);

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey().'&viaResource=posts&viaResourceId='.$post->id.'&viaRelationship=comments', [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals(1, ActionEvent::first()->model_id);
    }

    public function test_actions_can_be_applied_to_an_entire_resource_with_search_constraint()
    {
        $comment = factory(Comment::class)->create(['body' => 'Comment 1']);
        $comment2 = factory(Comment::class)->create(['body' => 'Comment 2']);

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey().'&search=Comment 1', [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals(1, ActionEvent::first()->model_id);
    }

    public function test_actions_can_be_applied_to_an_entire_resource_with_filter_constraint()
    {
        $comment = factory(Comment::class)->create();
        $comment2 = factory(Comment::class)->create();

        $filters = base64_encode(json_encode([
            [
                'class' => IdFilter::class,
                'value' => 1,
            ],
        ]));

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey().'&filters='.$filters, [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals(1, ActionEvent::first()->model_id);
    }

    public function test_actions_can_be_applied_to_an_entire_resource_with_search_and_filter_constraint()
    {
        $comment = factory(Comment::class)->create();
        $comment2 = factory(Comment::class)->create();

        $filters = base64_encode(json_encode([
            [
                'class' => IdFilter::class,
                'value' => 1,
            ],
        ]));

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey().'&search=Comment 2&filters='.$filters, [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_actions_can_be_applied_to_soft_deleted_resources()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $user->delete();
        $user2->delete();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new NoopAction)->uriKey().'&trashed=with', [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals($user2->id, NoopAction::$applied[0][0]->id);
        $this->assertEquals($user->id, NoopAction::$applied[0][1]->id);
        $this->assertCount(2, ActionEvent::all());
    }

    public function test_action_event_not_created_if_action_fails()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new ExceptionAction)->uriKey(), [
                            'resources' => $user->id,
                        ]);

        $response->assertStatus(500);
        $this->assertCount(0, ActionEvent::all());
    }

    public function test_actions_can_update_single_event_statuses()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new UpdateStatusAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                        ]);

        $response->assertStatus(200);
        $this->assertCount(2, ActionEvent::all());
        $this->assertEquals('failed', ActionEvent::where('model_id', $user->id)->first()->status);
        $this->assertEquals('finished', ActionEvent::where('model_id', $user2->id)->first()->status);
    }

    public function test_queued_actions_can_be_dispatched()
    {
        config(['queue.default' => 'sync']);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new QueuedAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);

        $this->assertEquals($user2->id, $_SERVER['queuedAction.applied'][0][0]->id);
        $this->assertEquals($user->id, $_SERVER['queuedAction.applied'][0][1]->id);
        $this->assertEquals('Taylor Otwell', $_SERVER['queuedAction.appliedFields'][0]->test);

        $this->assertCount(2, ActionEvent::all());
        $this->assertEquals('finished', ActionEvent::first()->status);
    }

    public function test_queued_actions_can_be_serialized_when_have_callbacks()
    {
        config(['queue.default' => 'sync']);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $_SERVER['nova.user.actionCallbacks'] = true;

        $response = $this->withExceptionHandling()
                         ->post('/nova-api/users/action?action='.(new QueuedAction)->uriKey(), [
                             'resources' => implode(',', [$user->id, $user2->id]),
                             'test' => 'Taylor Otwell',
                             'callback' => '',
                         ]);

        unset($_SERVER['nova.user.actionCallbacks']);

        $response->assertStatus(200);

        $this->assertCount(1, $_SERVER['queuedAction.applied'][0]);
        $this->assertEquals($user->id, $_SERVER['queuedAction.applied'][0][1]->id);
        $this->assertEquals('Taylor Otwell', $_SERVER['queuedAction.appliedFields'][0]->test);

        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals('finished', ActionEvent::first()->status);
    }

    public function test_queued_actions_can_be_dispatched_for_an_entire_resource()
    {
        config(['queue.default' => 'sync']);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new QueuedResourceAction)->uriKey(), [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals($user->id, $_SERVER['queuedResourceAction.applied'][0][0]->id);
        $this->assertEquals('Taylor Otwell', $_SERVER['queuedResourceAction.appliedFields'][0]->test);
    }

    public function test_queued_actions_can_be_dispatched_for_soft_deleted_resources()
    {
        config(['queue.default' => 'sync']);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $user->delete();
        $user2->delete();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new QueuedAction)->uriKey().'&trashed=with', [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals($user2->id, $_SERVER['queuedAction.applied'][0][0]->id);
        $this->assertEquals($user->id, $_SERVER['queuedAction.applied'][0][1]->id);
        $this->assertCount(2, ActionEvent::all());
    }

    public function test_queued_action_events_are_marked_as_waiting_before_being_processed()
    {
        config(['queue.default' => 'null']);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new QueuedAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                            'callback' => '',
                        ]);

        $response->assertStatus(200);

        $this->assertCount(2, ActionEvent::all());
        $this->assertEquals('waiting', ActionEvent::first()->status);
    }

    public function test_queued_actions_that_fail_are_marked_as_failed()
    {
        config(['queue.default' => 'redis']);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new FailingAction)->uriKey(), [
                            'resources' => $user->id,
                        ]);

        $response->assertStatus(200);
        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals('waiting', ActionEvent::first()->status);

        $this->work();

        $this->assertEquals('failed', ActionEvent::first()->status);
        $this->assertTrue(FailingAction::$failedForUser);
    }

    public function test_queued_actions_for_an_entire_resource_that_fail_are_marked_as_failed()
    {
        config(['queue.default' => 'redis']);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new FailingAction)->uriKey(), [
                            'resources' => 'all',
                        ]);

        $response->assertStatus(200);
        $this->assertCount(1, ActionEvent::all());
        $this->assertEquals('waiting', ActionEvent::first()->status);

        $this->work();

        $this->assertEquals('failed', ActionEvent::first()->status);
        $this->assertTrue(FailingAction::$failedForUser);
    }

    public function test_queued_actions_can_update_single_event_statuses()
    {
        config(['queue.default' => 'redis']);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new QueuedUpdateStatusAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                        ]);

        $response->assertStatus(200);
        $this->assertCount(2, ActionEvent::all());
        $this->assertEquals('waiting', ActionEvent::where('model_id', $user->id)->first()->status);
        $this->assertEquals('waiting', ActionEvent::where('model_id', $user2->id)->first()->status);

        $this->work();

        $this->assertEquals('failed', ActionEvent::where('model_id', $user->id)->first()->status);
        $this->assertEquals('finished', ActionEvent::where('model_id', $user2->id)->first()->status);
    }

    public function test_custom_apply_methods_may_be_defined_for_a_given_type()
    {
        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/comments/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => $comment->id,
                        ]);

        $response->assertStatus(200);
        $this->assertEquals($comment->id, NoopAction::$appliedToComments[0][0]->id);
        $this->assertEmpty(NoopAction::$applied);
    }

    public function test_exception_is_thrown_if_handle_method_is_missing()
    {
        $this->expectException(\Laravel\Nova\Exceptions\MissingActionHandlerException::class);
        $response = $this->withoutExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new EmptyAction)->uriKey(), [
                            'resources' => '1',
                        ]);
    }

    public function test_exception_is_thrown_if_handle_method_is_missing_for_entire_resource()
    {
        $this->expectException(\Laravel\Nova\Exceptions\MissingActionHandlerException::class);

        $response = $this->withoutExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new EmptyAction)->uriKey(), [
                            'resources' => 'all',
                        ]);
    }

    public function test_action_event_should_honor_custom_polymorphic_type_when_updating_status()
    {
        Relation::morphMap(['user' => User::class]);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/action?action='.(new UpdateStatusAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                        ]);

        $actionEvent = ActionEvent::where('model_id', $user->id)->first();

        $this->assertEquals('Update Status Action', $actionEvent->name);

        $this->assertEquals('failed', $actionEvent->status);

        $this->assertEquals('user', $actionEvent->actionable_type);
        $this->assertEquals($user->id, $actionEvent->actionable_id);

        $this->assertEquals('user', $actionEvent->target_type);
        $this->assertEquals($user->id, $actionEvent->target_id);

        $this->assertEquals('user', $actionEvent->model_type);
        $this->assertEquals($user->id, $actionEvent->model_id);

        $actionEvent2 = ActionEvent::where('model_id', $user2->id)->first();

        $this->assertEquals('Update Status Action', $actionEvent2->name);

        $this->assertEquals('finished', $actionEvent2->status);

        $this->assertEquals('user', $actionEvent2->actionable_type);
        $this->assertEquals($user2->id, $actionEvent2->actionable_id);

        $this->assertEquals('user', $actionEvent2->target_type);
        $this->assertEquals($user2->id, $actionEvent2->target_id);

        $this->assertEquals('user', $actionEvent2->model_type);
        $this->assertEquals($user2->id, $actionEvent2->model_id);

        Relation::morphMap([], false);
    }

    public function test_actions_can_ignore_action_event()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
            ->post('/nova-api/users/action?action='.(new NoopActionWithoutActionable())->uriKey(), [
                'resources' => implode(',', [$user->id, $user2->id]),
            ]);

        $response->assertStatus(200);

        $this->assertCount(0, ActionEvent::all());
    }

    public function test_actions_handle_result()
    {
        factory(User::class)->times(201)->create();

        $response = $this->withExceptionHandling()
            ->post('/nova-api/users/action?action='.(new HandleResultAction())->uriKey(), [
                'resources' => 'all',
            ]);

        $response->assertStatus(200);
        $this->assertEquals(['message' => 'Processed 201 records'], $response->original);
    }
}
