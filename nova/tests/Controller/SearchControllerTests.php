<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\User;

trait SearchControllerTests
{
    public function test_can_retrieve_search_results_for_all_searchable_resources()
    {
        $user = factory(User::class)->create();
        $post = factory(Post::class)->create(['user_id' => $user->id]);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/search?search=1');

        $response->assertStatus(200);

        $original = $response->original;

        $this->assertEquals('posts', $original[1]['resourceName']);
        $this->assertEquals('Post Resources', $original[1]['resourceTitle']);
        $this->assertEquals($post->id, $original[1]['title']);
        $this->assertEquals($user->id, $original[1]['resourceId']);
        $this->assertEquals('http://localhost/nova/resources/posts/'.$post->id, $original[1]['url']);
        $this->assertNull($original[1]['avatar']);

        $this->assertEquals('users', $original[2]['resourceName']);
        $this->assertEquals('User Resources', $original[2]['resourceTitle']);
        $this->assertEquals($user->id, $original[2]['title']);
        $this->assertEquals($user->id, $original[2]['resourceId']);
        $this->assertEquals('http://localhost/nova/resources/users/'.$user->id, $original[2]['url']);
        $this->assertNull($original[2]['avatar']);
    }

    public function test_can_retrieve_search_results_with_custom_cover()
    {
        $user = factory(User::class)->create();

        $_SESSION['nova.user.cover'] = true;

        $response = $this->withExceptionHandling()
            ->getJson('/nova-api/search?search=1');

        unset($_SESSION['nova.user.cover']);

        $response->assertStatus(200);

        $original = $response->original;

        $this->assertEquals('https://github.com/taylorotwell.png?size=40', $original[1]['avatar']);
    }
}
