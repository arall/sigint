<?php

namespace Laravel\Nova\Tests\Feature;

use Cake\Chronos\Chronos;
use Illuminate\Support\Carbon;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Metrics\Trend;
use Laravel\Nova\Metrics\Value;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\AverageWordCount;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\PostCountTrend;
use Laravel\Nova\Tests\Fixtures\PostWithCustomCreatedAt;
use Laravel\Nova\Tests\Fixtures\TotalUsers;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class MetricTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_metric_can_be_calculated()
    {
        factory(User::class, 2)->create();

        $this->assertEquals(2, (new TotalUsers)->calculate(NovaRequest::create('/'))->value);
    }

    public function test_metric_calculation_using_user_timezone()
    {
        $metric = new class extends Value {
            public function calculate(NovaRequest $request)
            {
                return $this->count($request, User::class);
            }
        };

        $now = Carbon::parse('Oct 14 2019 5 pm'); // UTC (future time)
        $nowCentral = $now->copy()->tz('America/Chicago'); // Now for the user

        Carbon::setTestNow(Carbon::parse($nowCentral));

        factory(User::class)->create(['created_at' => $now]);
        factory(User::class)->create(['created_at' => $nowCentral]);

        $request = NovaRequest::create('/', 'GET', ['timezone' => 'America/Chicago']);

        $this->assertEquals(1, $metric->calculate($request)->value);

        Carbon::setTestNow(null);
    }

    public function test_metric_calculation_uses_custom_timezone()
    {
        Nova::userTimezone(function () {
            return 'UTC';
        });

        $metric = new class extends Value {
            public function calculate(NovaRequest $request)
            {
                return $this->count($request, User::class);
            }
        };

        $now = Carbon::parse('Oct 14 2019 5 pm'); // UTC (future time)
        $nowCentral = $now->copy()->tz('America/Chicago'); // Now for the user

        Carbon::setTestNow(Carbon::parse($nowCentral));

        factory(User::class)->create(['created_at' => $now]);
        factory(User::class)->create(['created_at' => $nowCentral]);

        // Note even if we send the user's timezone, it should still use UTC
        $request = NovaRequest::create('/', 'GET', ['timezone' => 'America/Chicago']);

        $this->assertEquals(2, $metric->calculate($request)->value);

        Carbon::setTestNow(null);

        Nova::userTimezone(null);
    }

    public function test_trend_with_custom_created_at()
    {
        factory(Post::class, 2)->create();

        $post = Post::find(1);
        $post->published_at = Chronos::now();
        $post->save();

        $post = Post::find(2);
        $post->published_at = Chronos::now()->subDay(1);
        $post->save();

        $this->assertEquals([1, 1], array_values((new PostCountTrend())->countByDays(NovaRequest::create('/?range=2'), new PostWithCustomCreatedAt)->trend));
    }

    public function test_trend_calculation_using_user_timezone()
    {
        $metric = new class extends Trend {
        };

        Chronos::setTestNow(Chronos::parse('Dec 14 2019', 'UTC'));

        $now = Chronos::parse('Nov 1 2019 6:30 AM', 'UTC');

        $nowCentral = Chronos::parse('Nov 2 2019 12 AM', 'UTC');

        factory(User::class, 2)->create(['created_at' => $now]);
        factory(User::class, 7)->create(['created_at' => $nowCentral]);

        $request = NovaRequest::create('/?range=2', 'GET', ['timezone' => 'America/Chicago']);
        $this->assertEquals([0, 9], array_values($metric->countByMonths($request, User::class)->trend));

        $request = NovaRequest::create('/?range=2', 'GET', ['timezone' => 'America/Los_Angeles']);
        $this->assertEquals([2, 7], array_values($metric->countByMonths($request, User::class)->trend));

        Chronos::setTestNow(null);
    }

    public function test_trend_calculation_using_custom_timezone()
    {
        Nova::userTimezone(function () {
            return 'UTC';
        });

        $metric = new class extends Trend {
        };

        Chronos::setTestNow(Chronos::parse('Dec 14 2019', 'UTC'));

        $now = Chronos::parse('Nov 1 2019 6:30 AM', 'UTC');

        $nowCentral = Chronos::parse('Nov 2 2019 12 AM', 'UTC');

        factory(User::class, 2)->create(['created_at' => $now]);
        factory(User::class, 7)->create(['created_at' => $nowCentral]);

        $request = NovaRequest::create('/?range=2', 'GET', ['timezone' => 'America/Chicago']);
        $this->assertEquals([9, 0], array_values($metric->countByMonths($request, User::class)->trend));

        $request = NovaRequest::create('/?range=2', 'GET', ['timezone' => 'America/Los_Angeles']);
        $this->assertEquals([9, 0], array_values($metric->countByMonths($request, User::class)->trend));

        Chronos::setTestNow(null);

        Nova::userTimezone(null);
    }

    public function test_metrics_can_be_set_to_refresh_automatically()
    {
        $metric = new PostCountTrend;

        $this->assertfalse($metric->jsonSerialize()['refreshWhenActionRuns']);

        $metric->refreshWhenActionRuns();

        $this->assertTrue($metric->jsonSerialize()['refreshWhenActionRuns']);

        $metric->refreshWhenActionRuns(false);

        $this->assertFalse($metric->jsonSerialize()['refreshWhenActionRuns']);
    }

    public function test_value_metrics_default_precision()
    {
        $averageWordCount = factory(Post::class, 2)->create()->average('word_count');
        $this->assertEquals($averageWordCount, (new AverageWordCount)->calculate(NovaRequest::create('/'))->value);
    }

    public function test_value_metrics_custom_precision()
    {
        $averageWordCount = factory(Post::class, 2)->create(['word_count' => 5.37894])->average('word_count');
        $this->assertEquals($averageWordCount, 5.37894);
        $this->assertEquals(5.38, (new AverageWordCount)->precision(2)->calculate(NovaRequest::create('/'))->value);
    }

    public function test_value_metrics_can_provide_a_default_range()
    {
        $metric = new TotalUsers;

        $metric->ranges = [
            1 => 'January',
            2 => 'February',
        ];

        $metric->defaultRange(1);

        $this->assertEquals(1, $metric->jsonSerialize()['selectedRangeKey']);
    }

    public function test_value_metrics_default_range_defaults_to_null()
    {
        $metric = new TotalUsers;

        $this->assertNull($metric->jsonSerialize()['selectedRangeKey']);
    }
}
