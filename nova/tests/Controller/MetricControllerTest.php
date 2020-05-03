<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Carbon;
use Laravel\Nova\Metrics\Metric;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\TotalUsers;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserGrowth;
use Laravel\Nova\Tests\IntegrationTest;

class MetricControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_available_cards_can_be_retrieved()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/cards');

        $response->assertStatus(200);
        $this->assertEquals('value-metric', $response->original[0]->jsonSerialize()['component']);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
        $this->assertEquals((new TotalUsers)->uriKey(), $response->original[0]->jsonSerialize()['uriKey']);
        $this->assertFalse($response->original[0]->jsonSerialize()['onlyOnDetail']);
    }

    public function test_available_metrics_can_be_retrieved()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics');

        $response->assertStatus(200);
        $this->assertEquals('value-metric', $response->original[0]->jsonSerialize()['component']);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
        $this->assertEquals((new TotalUsers)->uriKey(), $response->original[0]->jsonSerialize()['uriKey']);
        $this->assertFalse($response->original[0]->jsonSerialize()['onlyOnDetail']);
    }

    public function test_available_metrics_cant_be_retrieved_if_not_authorized_to_view_resource()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/forbidden-users/metrics');

        $response->assertStatus(403);
    }

    public function test_unauthorized_metrics_are_not_returned()
    {
        $_SERVER['nova.totalUsers.canSee'] = false;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics');

        unset($_SERVER['nova.totalUsers.canSee']);

        $response->assertStatus(200);
        $this->assertCount(2, $response->original);
        $this->assertEquals(UserGrowth::class, $response->original[0]->jsonSerialize()['class']);
    }

    public function test_can_retrieve_metric_value()
    {
        factory(User::class, 2)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/total-users');

        $response->assertStatus(200);
        $this->assertEquals(2, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_detail_only_metric_value()
    {
        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/'.$user->id.'/metrics/customer-revenue');

        $response->assertStatus(200);
        $this->assertEquals(100, $response->original['value']);
        $this->assertEquals(1, $_SERVER['nova.customerRevenue.user']->id);

        unset($_SERVER['nova.customerRevenue.user']);
    }

    public function test_cant_retrieve_unauthorized_metric_values()
    {
        $_SERVER['nova.totalUsers.canSee'] = false;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/total-users');

        unset($_SERVER['nova.totalUsers.canSee']);

        $response->assertStatus(404);
    }

    public function test_available_dashboard_cards_can_be_retrieved()
    {
        Nova::cards([new TotalUsers]);

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/cards');

        $response->assertStatus(200);
        $this->assertInstanceOf(Metric::class, $response->original[0]);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
    }

    public function test_available_dashboard_metrics_can_be_retrieved()
    {
        Nova::cards([new TotalUsers]);

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/metrics');

        $response->assertStatus(200);
        $this->assertInstanceOf(Metric::class, $response->original[0]);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
    }

    public function test_can_retrieve_dashboard_metric_value()
    {
        Nova::cards([new TotalUsers]);

        $user = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/metrics/total-users');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
    }

    public function test_can_retrieve_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->created_at = now()->subDays(31);
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=30');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_custom_column_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->updated_at = now()->subDays(31);
        $user->save();

        $_SERVER['__nova.userGrowthColumn'] = 'updated_at';

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=30');

        unset($_SERVER['__nova.userGrowthColumn']);

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_today_count_calculations()
    {
        Carbon::setTestNow('Oct 1 12:00 PM');

        factory(User::class, 3)->create();

        $user = User::find(1);
        $user->created_at = now()->setTime(1, 0, 0);
        $user->save();

        $user = User::find(2);
        $user->created_at = now()->setTime(3, 0, 0);
        $user->save();

        $user = User::find(3);
        $user->created_at = now()->yesterday();
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=TODAY');

        $response->assertStatus(200);
        $this->assertEquals(2, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);

        Carbon::setTestNow();
    }

    public function test_can_retrieve_mtd_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->created_at = now()->subMonthsNoOverflow(1)->firstOfMonth();
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=MTD');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_qtd_count_calculations()
    {
        factory(User::class, 3)->create();

        $user = User::find(2);
        $user->created_at = $this->getFirstDayOfPreviousQuarter();
        $user->save();

        $user = User::find(3);
        $user->created_at = $this->getFirstDayOfPreviousQuarter();
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=QTD');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(2, $response->original['value']->previous);
    }

    public function test_can_retrieve_ytd_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->created_at = now()->subYearsNoOverflow(1)->firstOfYear();
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/metrics/user-growth?range=YTD');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_average_calculations()
    {
        factory(Post::class, 2)->create(['word_count' => 100]);

        $post = Post::find(2);
        $post->created_at = now()->subDays(35);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-word-count?range=30');

        $response->assertStatus(200);
        $this->assertEquals(100, $response->original['value']->value);
        $this->assertEquals(100, $response->original['value']->previous);
    }

    public function test_can_retrieve_today_average_calculations()
    {
        factory(Post::class, 3)->create(['word_count' => 100]);

        $post = Post::find(2);
        $post->word_count = 50;
        $post->created_at = now()->setTime(1, 0, 0);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-word-count?range=TODAY');

        $response->assertStatus(200);
        $this->assertEquals(83, $response->original['value']->value);
        $this->assertEquals(0, $response->original['value']->previous);
    }

    public function test_can_retrieve_mtd_average_calculations()
    {
        factory(Post::class, 2)->create(['word_count' => 100]);

        $post = Post::find(2);
        $post->word_count = 50;
        $post->created_at = now()->subMonthsNoOverflow(1)->firstOfMonth();
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-word-count?range=MTD');

        $response->assertStatus(200);
        $this->assertEquals(100, $response->original['value']->value);
        $this->assertEquals(50, $response->original['value']->previous);
    }

    public function test_can_retrieve_qtd_average_calculations()
    {
        factory(Post::class, 2)->create(['word_count' => 100]);

        $post = Post::find(2);
        $post->word_count = 50;
        $post->created_at = $this->getFirstDayOfPreviousQuarter();
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-word-count?range=QTD');

        $response->assertStatus(200);
        $this->assertEquals(100, $response->original['value']->value);
        $this->assertEquals(50, $response->original['value']->previous);
    }

    public function test_can_retrieve_ytd_average_calculations()
    {
        factory(Post::class, 2)->create(['word_count' => 100]);

        $post = Post::find(2);
        $post->word_count = 50;
        $post->created_at = now()->subYearsNoOverflow(1)->firstOfYear();
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-word-count?range=YTD');

        $response->assertStatus(200);
        $this->assertEquals(100, $response->original['value']->value);
        $this->assertEquals(50, $response->original['value']->previous);
    }

    protected function getFirstDayOfPreviousQuarter()
    {
        return Carbon::firstDayOfPreviousQuarter();
    }
}
