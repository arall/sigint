<?php

namespace Laravel\Nova\Tests\Controller;

use Cake\Chronos\Chronos;
use Laravel\Nova\Metrics\Trend;
use Laravel\Nova\Tests\Fixtures\Post;

trait TrendDateTests
{
    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_month($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMonths(5);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6');

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subMonths(5)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(4)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(3)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(2)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(1)->format('F Y')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_month_by_user($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 4)->create();

        $post = Post::find(1);
        $post->user_id = 1;
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->user_id = 1;
        $post->created_at = Chronos::now()->subMonths(5);
        $post->save();

        // This is kind of a mis-use of the resourceId here since I'm giving it a user-id... but it fits the purpose of this test easily...
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/1/metrics/post-count-trend?range=6');

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subMonths(5)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(4)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(3)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(2)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMonths(1)->format('F Y')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_month_with_timezone($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMonths(5);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&timezone=America/Chicago');

        $response->assertStatus(200);

        $this->assertCount(6, $response->original['value']->trend);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMonths(5)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMonths(4)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMonths(3)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMonths(2)->format('F Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMonths(1)->format('F Y')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_week($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subWeeks(5)->addDays(3);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_WEEKS;

        $response = $this->withoutExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $startingDate = Chronos::now()->subWeeks(5)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->subWeeks(5)->addDays(3)->endOfWeek();
        $this->assertEquals(1, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->subWeeks(4)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->subWeeks(4)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->subWeeks(3)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->subWeeks(3)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->subWeeks(2)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->subWeeks(2)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->startOfWeek();
        $endingDate = Chronos::now()->endOfWeek();

        $this->assertEquals(1, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_week_with_timezone($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subWeeks(5)->addDays(3);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_WEEKS;

        $response = $this->withoutExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&timezone=America/Chicago');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertCount(6, $response->original['value']->trend);

        $startingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(5)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(5)->addDays(3)->endOfWeek();
        $this->assertEquals(1, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(4)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(4)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(3)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(3)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(2)->addDays(3)->startOfWeek();
        $endingDate = Chronos::now()->setTimezone('America/Chicago')->subWeeks(2)->addDays(3)->endOfWeek();
        $this->assertEquals(0, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        $startingDate = Chronos::now()->setTimezone('America/Chicago')->startOfWeek();
        $endingDate = Chronos::now()->setTimezone('America/Chicago')->endOfWeek();

        $this->assertEquals(1, $response->original['value']->trend[$startingDate->format('F j').' - '.$endingDate->format('F j')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_days($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subDays(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_DAYS;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subDays(4)->format('F j, Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subDays(3)->format('F j, Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subDays(2)->format('F j, Y')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subDays(1)->format('F j, Y')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F j, Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_hours($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subHours(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_HOURS;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subHours(4)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subHours(3)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subHours(2)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subHours(1)->format('F j - G:00')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F j - G:00')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_hours_with_timezone($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subHours(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_HOURS;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&timezone=America/Chicago');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertCount(6, $response->original['value']->trend);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subHours(4)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subHours(3)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subHours(2)->format('F j - G:00')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subHours(1)->format('F j - G:00')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->format('F j - G:00')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_minute($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMinutes(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_MINUTES;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subMinutes(4)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(3)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(2)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(1)->format('F j - G:i')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F j - G:i')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_minute_with_timezone($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMinutes(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_MINUTES;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&timezone=America/Chicago');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertCount(6, $response->original['value']->trend);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(4)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(3)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(2)->format('F j - G:i')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(1)->format('F j - G:i')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->format('F j - G:i')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_minute_in_12_hour_time($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMinutes(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_MINUTES;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&twelveHourTime=true');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->subMinutes(4)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(3)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(2)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->subMinutes(1)->format('F j - g:i A')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->format('F j - g:i A')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_count_can_be_retrieved_by_minute_in_12_hour_time_and_timezone($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->created_at = Chronos::now()->subMinutes(4);
        $post->save();

        $_SERVER['nova.postCountUnit'] = Trend::BY_MINUTES;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-count-trend?range=6&twelveHourTime=true&timezone=America/Chicago');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);

        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(4)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(3)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(2)->format('F j - g:i A')]);
        $this->assertEquals(0, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->subMinutes(1)->format('F j - g:i A')]);
        $this->assertEquals(1, $response->original['value']->trend[Chronos::now()->setTimezone('America/Chicago')->format('F j - g:i A')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_average_can_be_retrieved_by_month($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 3)->create(['word_count' => 100]);

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 200;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $post = Post::find(3);
        $post->word_count = 100;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-average-trend?range=6');

        $response->assertStatus(200);

        $this->assertEquals(150, $response->original['value']->trend[Chronos::now()->subMonths(5)->addDays(3)->format('F Y')]);
        $this->assertEquals(100, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_sum_can_be_retrieved_by_month($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 3)->create(['word_count' => 100]);

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 200;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $post = Post::find(3);
        $post->word_count = 100;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-sum-trend?range=6');

        $response->assertStatus(200);
        $this->assertEquals(300, $response->original['value']->trend[Chronos::now()->subMonths(5)->addDays(3)->format('F Y')]);
        $this->assertEquals(100, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_sum_can_be_retrieved_by_hour($date)
    {
        $_SERVER['nova.postCountUnit'] = 'hour';

        Chronos::setTestNow($date);

        factory(Post::class, 5)->create(['word_count' => 100]);

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 25000;
        $post->created_at = Chronos::now()->subHours(4);
        $post->save();

        $post = Post::find(3);
        $post->word_count = 25000;
        $post->created_at = Chronos::now()->subHours(4);
        $post->save();

        $post = Post::find(4);
        $post->word_count = 150;
        $post->created_at = Chronos::now()->subHour(5);
        $post->save();

        $post = Post::find(5);
        $post->word_count = 500;
        $post->created_at = Chronos::now()->subHour(5);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-sum-trend?range=6');

        unset($_SERVER['nova.postCountUnit']);

        $response->assertStatus(200);
        $this->assertEquals(650, $response->original['value']->trend[Chronos::now()->subHours(5)->format('F j - G:00')]);
        $this->assertEquals(50000, $response->original['value']->trend[Chronos::now()->subHours(4)->format('F j - G:00')]);
        $this->assertEquals(100, $response->original['value']->trend[Chronos::now()->format('F j - G:00')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_max_can_be_retrieved_by_month($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 3)->create(['word_count' => 100]);

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 500;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $post = Post::find(3);
        $post->word_count = 100;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-max-trend?range=6');

        $response->assertStatus(200);
        $this->assertEquals(500, $response->original['value']->trend[Chronos::now()->subMonths(5)->addDays(3)->format('F Y')]);
        $this->assertEquals(100, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    /**
     * @dataProvider trendDateProvider
     */
    public function test_trend_min_can_be_retrieved_by_month($date)
    {
        Chronos::setTestNow($date);

        factory(Post::class, 3)->create(['word_count' => 100]);

        $post = Post::find(1);
        $post->created_at = $date;
        $post->save();

        $post = Post::find(2);
        $post->word_count = 50;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $post = Post::find(3);
        $post->word_count = 100;
        $post->created_at = Chronos::now()->subMonths(5)->addDays(3);
        $post->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/posts/metrics/post-min-trend?range=6');

        $response->assertStatus(200);
        $this->assertEquals(50, $response->original['value']->trend[Chronos::now()->subMonths(5)->addDays(3)->format('F Y')]);
        $this->assertEquals(100, $response->original['value']->trend[Chronos::now()->format('F Y')]);

        Chronos::setTestNow();
    }

    public function trendDateProvider()
    {
        return [
            [Chronos::create(2018, 12, 31)],
            [Chronos::create(2018, 12, 31, 23, 59, 59)],
            [Chronos::create(2018, 12, 31, 13, 0, 0)],
            [Chronos::create(2018, 2, 28)],
            [Chronos::create(2018, 1, 1)],
        ];
    }
}
