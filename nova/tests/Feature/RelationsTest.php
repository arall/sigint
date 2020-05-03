<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\BelongsTo;
use Laravel\Nova\Fields\HasMany;
use Laravel\Nova\Fields\MorphTo;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\Comment;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\PostResource;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;

class RelationsTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_unset_belongs_to_after_update()
    {
        $user1 = factory(User::class)->create();
        $user2 = factory(User::class)->create();
        /** @var Post $post */
        $post = factory(Post::class)->create()->user()->associate($user1);

        $this->assertTrue($post->relationLoaded('user'));

        $request = tap(new NovaRequest([], [
            'user' => $user2->id,
        ]))->setMethod('POST');

        BelongsTo::make('User', 'user', UserResource::class)->fill($request, $post);

        $this->assertFalse($post->relationLoaded('user'));

        $this->assertEquals($post->user_id, $user2->id);
    }

    public function test_unset_morph_to_after_update()
    {
        $post1 = factory(Post::class)->create();
        $post2 = factory(Post::class)->create();

        /** @var Post $post */
        $comment = factory(Comment::class)->create()->commentable()->associate($post1);

        $this->assertTrue($comment->relationLoaded('commentable'));

        $request = tap(new NovaRequest([], [
            'commentable_type' => PostResource::uriKey(),
            'commentable' => $post2->id,
        ]))->setMethod('POST');

        MorphTo::make('Commentable', 'commentable')->fill($request, $comment);

        $this->assertFalse($comment->relationLoaded('commentable'));

        $this->assertEquals($comment->commentable_id, $post2->id);
    }

    public function test_changing_field_attribute_by_meta()
    {
        $field = HasMany::make('Post', 'posts', UserResource::class)->withMeta(['listable' => false]);

        $this->assertFalse($field->jsonSerialize()['listable']);
    }
}
