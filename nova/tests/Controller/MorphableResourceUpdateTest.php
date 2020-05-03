<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Tests\Fixtures\Comment;
use Laravel\Nova\Tests\Fixtures\CommentPolicy;
use Laravel\Nova\Tests\IntegrationTest;

class MorphableResourceUpdateTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_update_resources()
    {
        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/comments/'.$comment->id, [
                            'commentable' => $comment->commentable->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Updated Comment Body',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Updated Comment Body', $comment->fresh()->body);
    }

    public function test_can_update_resources_if_not_authorized_to_update()
    {
        $_SERVER['nova.comment.authorizable'] = true;
        $_SERVER['nova.comment.updatable'] = false;

        Gate::policy(Comment::class, CommentPolicy::class);

        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/comments/'.$comment->id, [
                            'commentable' => $comment->commentable->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Updated Comment Body',
                        ]);

        unset($_SERVER['nova.comment.authorizable']);
        unset($_SERVER['nova.comment.updatable']);

        $response->assertStatus(403);
        $this->assertNotEquals('Updated Comment Body', $comment->fresh()->body);
    }

    public function test_morphable_resource_must_exist()
    {
        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/comments/'.$comment->id, [
                            'commentable' => 100,
                            'commentable_type' => 'posts',
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['commentable']);
    }

    public function test_morphable_type_must_be_valid()
    {
        $comment = factory(Comment::class)->create();

        $response = $this->withExceptionHandling()
                        ->putJson('/nova-api/comments/'.$comment->id, [
                            'commentable' => 100,
                            'commentable_type' => 'videos',
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['commentable_type']);
    }
}
