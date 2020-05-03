<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class PartitionMetricControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_count_results_can_be_retrieved()
    {
        $user = factory(User::class)->create();
        factory(Post::class, 2)->create(['user_id' => $user->id]);

        $user->name = 'Taylor Otwell';
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/posts-by-user');

        $response->assertStatus(200);
        $this->assertEquals(['Taylor Otwell' => 2], $response->original['value']->value);
    }

    public function test_average_results_can_be_retrieved()
    {
        $user = factory(User::class)->create();
        factory(Post::class, 2)->create(['user_id' => $user->id]);

        $user->name = 'Taylor Otwell';
        $user->save();

        $post = Post::find(1);
        $post->word_count = 100;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 200;
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/word-count-by-user');

        $response->assertStatus(200);
        $this->assertEquals([$user->id => 150], $response->original['value']->value);
    }
}
