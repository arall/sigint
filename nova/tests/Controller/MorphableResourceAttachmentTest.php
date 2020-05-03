<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\Tag;
use Laravel\Nova\Tests\IntegrationTest;

class MorphableResourceAttachmentTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_attach_resources()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach-morphed/tags', [
                            'tags' => $tag->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(200);

        $this->assertCount(1, $post->fresh()->tags);
        $this->assertEquals($tag->id, $post->fresh()->tags->first()->id);
        $this->assertEquals('Y', $post->fresh()->tags->first()->pivot->admin);
    }

    public function test_cant_attach_resources_that_arent_relatable()
    {
        $post = factory(Post::class)->create();

        $tag = factory(Tag::class)->create();
        $tag2 = factory(Tag::class)->create();
        $tag3 = factory(Tag::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach-morphed/tags', [
                            'tags' => $tag3->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $this->assertCount(0, $post->fresh()->tags);
        $this->assertFalse(isset($_SERVER['nova.post.relatableTags']));
    }

    public function test_resource_may_specify_custom_relatable_query_customizer()
    {
        $post = factory(Post::class)->create();

        $tag = factory(Tag::class)->create();
        $tag2 = factory(Tag::class)->create();
        $tag3 = factory(Tag::class)->create();

        $_SERVER['nova.post.useCustomRelatableTags'] = true;
        unset($_SERVER['nova.post.relatableTags']);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach-morphed/tags', [
                            'tags' => $tag3->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'tags',
                        ]);

        unset($_SERVER['nova.post.useCustomRelatableTags']);

        $this->assertNotNull($_SERVER['nova.post.relatableTags']);
        $response->assertStatus(422);
        $this->assertCount(0, $post->fresh()->tags);

        unset($_SERVER['nova.post.relatableTags']);
    }

    public function test_attached_resource_must_exist()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach/tags', [
                            'tags' => 100,
                            'admin' => 'Y',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['tags']);

        $this->assertCount(0, $post->fresh()->tags);
    }

    public function test_attached_resource_must_not_already_be_attached()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();
        $post->tags()->attach($tag);

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach/tags', [
                            'tags' => $tag->id,
                            'admin' => 'Y',
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['tags']);

        $this->assertCount(1, $post->fresh()->tags);
    }

    public function test_pivot_data_is_validated()
    {
        $post = factory(Post::class)->create();
        $tag = factory(Tag::class)->create();

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/posts/'.$post->id.'/attach/tags', [
                            'tags' => $tag->id,
                            'viaRelationship' => 'tags',
                        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['admin']);
    }
}
