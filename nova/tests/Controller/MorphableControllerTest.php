<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\IntegrationTest;

class MorphableControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_retrieve_morphable_resources()
    {
        $post = factory(Post::class)->create(['title' => 'a']);
        $post2 = factory(Post::class)->create(['title' => 'b']);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/comments/morphable/commentable?type=posts');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 1, 'display' => $post->title],
            ['value' => 2, 'display' => $post2->title],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_can_retrieve_morphable_resources_by_search()
    {
        $post = factory(Post::class)->create(['title' => 'a']);
        $post2 = factory(Post::class)->create(['title' => 'b']);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/comments/morphable/commentable?type=posts&search=b');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => $post2->title],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }

    public function test_only_the_first_matching_record_may_be_retrieved()
    {
        $post = factory(Post::class)->create(['title' => 'a']);
        $post2 = factory(Post::class)->create(['title' => 'b']);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/comments/morphable/commentable?type=posts&current=2&first=true');

        $response->assertStatus(200);

        $response->assertJsonStructure([
            'resources', 'softDeletes', 'withTrashed',
        ]);

        $this->assertEquals([
            ['value' => 2, 'display' => $post2->title],
        ], $response->original['resources']->all());

        $this->assertFalse($response->original['softDeletes']);
        $this->assertFalse($response->original['withTrashed']);
    }
}
