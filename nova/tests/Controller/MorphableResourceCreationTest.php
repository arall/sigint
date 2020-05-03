<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\Gate;
use Laravel\Nova\Tests\Fixtures\Comment;
use Laravel\Nova\Tests\Fixtures\CommentPolicy;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\IntegrationTest;

class MorphableResourceCreationTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_create_resources()
    {
        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => $post->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(201);
        $this->assertEquals(Comment::first()->commentable->title, $post->title);
    }

    public function test_cant_create_resources_if_not_authorized_to_create()
    {
        $_SERVER['nova.comment.authorizable'] = true;
        $_SERVER['nova.comment.creatable'] = false;

        Gate::policy(Comment::class, CommentPolicy::class);

        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => $post->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Comment Body',
                        ]);

        unset($_SERVER['nova.comment.authorizable']);
        unset($_SERVER['nova.comment.creatable']);

        $response->assertStatus(403);
    }

    public function test_cant_create_resources_if_parent_resource_is_not_relatable()
    {
        $post = factory(Post::class)->create();
        $post2 = factory(Post::class)->create();
        $post3 = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => $post3->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(422);
        $this->assertFalse(isset($_SERVER['nova.post.relatablePosts']));
    }

    public function test_resource_may_specify_custom_relatable_query_customizer()
    {
        $post = factory(Post::class)->create();
        $post2 = factory(Post::class)->create();
        $post3 = factory(Post::class)->create();

        $_SERVER['nova.comment.useCustomRelatablePosts'] = true;
        unset($_SERVER['nova.post.relatablePosts']);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => $post3->id,
                            'commentable_type' => 'posts',
                            'author' => 1,
                            'body' => 'Comment Body',
                        ]);

        unset($_SERVER['nova.comment.useCustomRelatablePosts']);

        $this->assertNotNull($_SERVER['nova.comment.relatablePosts']);
        $response->assertStatus(422);

        unset($_SERVER['nova.comment.relatablePosts']);
    }

    public function test_morphable_resource_must_exist()
    {
        $post = factory(Post::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => 100,
                            'commentable_type' => 'posts',
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['commentable']);
    }

    public function test_morphable_type_must_be_valid()
    {
        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/comments', [
                            'commentable' => 100,
                            'commentable_type' => 'videos',
                            'body' => 'Comment Body',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['commentable_type']);
    }
}
