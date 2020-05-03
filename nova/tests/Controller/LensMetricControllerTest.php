<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Carbon;
use Laravel\Nova\Tests\Fixtures\TotalUsers;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserGrowth;
use Laravel\Nova\Tests\IntegrationTest;

class LensMetricControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_available_cards_can_be_retrieved()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/cards');

        $response->assertStatus(200);
        $this->assertEquals('value-metric', $response->original[0]->jsonSerialize()['component']);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
        $this->assertEquals((new TotalUsers)->uriKey(), $response->original[0]->jsonSerialize()['uriKey']);
        $this->assertFalse($response->original[0]->jsonSerialize()['onlyOnDetail']);
    }

    public function test_available_metrics_can_be_retrieved()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics');

        $response->assertStatus(200);
        $this->assertEquals('value-metric', $response->original[0]->jsonSerialize()['component']);
        $this->assertEquals(TotalUsers::class, $response->original[0]->jsonSerialize()['class']);
        $this->assertEquals((new TotalUsers)->uriKey(), $response->original[0]->jsonSerialize()['uriKey']);
        $this->assertFalse($response->original[0]->jsonSerialize()['onlyOnDetail']);
    }

    public function test_available_metrics_cant_be_retrieved_if_not_authorized_to_view_resource()
    {
        $_SERVER['nova.authorize.forbidden-user-lens'] = false;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics');

        unset($_SERVER['nova.authorize.forbidden-user-lens']);

        $response->assertStatus(403);
    }

    public function test_unauthorized_metrics_are_not_returned()
    {
        $_SERVER['nova.totalUsers.canSee'] = false;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics');

        unset($_SERVER['nova.totalUsers.canSee']);

        $response->assertStatus(200);
        $this->assertCount(2, $response->original);
        $this->assertEquals(UserGrowth::class, $response->original[0]->jsonSerialize()['class']);
    }

    public function test_can_retrieve_metric_value()
    {
        factory(User::class, 2)->create();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics/total-users');

        $response->assertStatus(200);
        $this->assertEquals(2, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_cant_retrieve_unauthorized_metric_values()
    {
        $_SERVER['nova.totalUsers.canSee'] = false;

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics/total-users');

        unset($_SERVER['nova.totalUsers.canSee']);

        $response->assertStatus(404);
    }

    public function test_can_retrieve_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->created_at = now()->subDays(31);
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics/user-growth?range=30');

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
                        ->get('/nova-api/users/lens/user-lens/metrics/user-growth?range=30');

        unset($_SERVER['__nova.userGrowthColumn']);

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    public function test_can_retrieve_mtd_count_calculations()
    {
        factory(User::class, 2)->create();

        $user = User::find(2);
        $user->created_at = now()->subMonthsNoOverflow(1)->firstOfMonth();
        $user->save();

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/users/lens/user-lens/metrics/user-growth?range=MTD');

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
                        ->get('/nova-api/users/lens/user-lens/metrics/user-growth?range=QTD');

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
                        ->get('/nova-api/users/lens/user-lens/metrics/user-growth?range=YTD');

        $response->assertStatus(200);
        $this->assertEquals(1, $response->original['value']->value);
        $this->assertEquals(1, $response->original['value']->previous);
    }

    protected function getFirstDayOfPreviousQuarter()
    {
        return Carbon::firstDayOfPreviousQuarter();
    }
}
