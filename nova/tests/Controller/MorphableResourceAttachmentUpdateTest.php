<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\Tag;
use Laravel\Nova\Tests\IntegrationTest;

class MorphableResourceAttachmentUpdateTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_update_attached_resources()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();
        $post->tags()->attach($tag, ['admin' => 'Y']);

        $this->assertEquals('Y', $post->fresh()->tags->first()->pivot->admin);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/update-attached/tags/'.$tag->id, [
                            'tags' => $tag->id,
                            'admin' => 'N',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(200);

        $this->assertCount(1, $post->fresh()->tags);
        $this->assertEquals($tag->id, $post->fresh()->tags->first()->id);
        $this->assertEquals('N', $post->fresh()->tags->first()->pivot->admin);
    }

    public function test_cant_update_attached_resources_if_not_related_resource_is_not_relatable()
    {
        $post = factory(Post::class)->create();

        $tag = factory(Tag::class)->create();
        $tag2 = factory(Tag::class)->create();
        $tag3 = factory(Tag::class)->create();

        $post->tags()->attach($tag3, ['admin' => 'Y']);

        $this->assertEquals('Y', $post->fresh()->tags->first()->pivot->admin);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/update-attached/tags/'.$tag->id, [
                            'tags' => $tag3->id,
                            'admin' => 'N',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $this->assertEquals('Y', $post->fresh()->tags->first()->pivot->admin);
    }

    public function test_404_is_returned_if_resource_is_not_attached()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();
        $post->tags()->attach($tag);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/update-attached/tags/100', [
                            'tags' => $tag->id,
                            'admin' => 'N',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(404);
    }

    public function test_pivot_data_is_validated()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();
        $post->tags()->attach($tag);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/update-attached/tags/'.$tag->id, [
                            'tags' => $tag->id,
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['admin']);
    }
}
