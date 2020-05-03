<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\LensFieldValidationAction;
use Laravel\Nova\Tests\Fixtures\NoopAction;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class LensActionControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_retrieve_actions_for_a_lens()
    {
        $response = $this->withExceptionHandling()
            ->get('/nova-api/users/lens/user-lens/actions');

        $response->assertStatus(200);
        $this->assertCount(2, $response->original['actions']);
        $this->assertInstanceOf(NoopAction::class, $response->original['actions'][0]);
        $this->assertInstanceOf(LensFieldValidationAction::class, $response->original['actions'][1]);
    }

    public function test_lens_actions_can_be_applied()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/lens/user-lens/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => implode(',', [$user->id, $user2->id]),
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals(['message' => 'Hello World'], $response->original);
    }

    public function test_lens_actions_can_be_applied_to_entire_lens()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withExceptionHandling()
                        ->post('/nova-api/users/lens/user-lens/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => 'all',
                            'test' => 'Taylor Otwell',
                        ]);

        $response->assertStatus(200);
        $this->assertEquals('Taylor Otwell', NoopAction::$appliedFields[0]->test);
    }

    public function test_lens_actions_cant_be_applied_to_entire_lens_if_lens_returns_resource()
    {
        $this->expectException(\LogicException::class);

        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $response = $this->withoutExceptionHandling()
                        ->post('/nova-api/users/lens/paginating-user-lens/action?action='.(new NoopAction)->uriKey(), [
                            'resources' => 'all',
                        ]);
    }

    public function test_lens_actions_validation_rules_are_applied()
    {
        $response = $this->withExceptionHandling()
            ->postJson('/nova-api/users/lens/user-lens/action?action=lens-field-validation-action', [
                'reason' => '',
            ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors([
            'reason',
        ]);
    }
}
