<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\Fixtures\Boolean;
use Laravel\Nova\Tests\IntegrationTest;

class BooleanResourceTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_create_boolean_resource_with_true_value()
    {
        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/booleans', [
                            'active' => true,
                        ]);

        $response->assertStatus(201);

        $boolean = Boolean::first();
        $this->assertEquals('Yes', $boolean->active);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/booleans/1');

        $response->assertStatus(200);
        $fields = $response->original['resource']['fields'];
        $this->assertTrue(collect($fields)->where('attribute', 'active')->first()->value);
    }

    public function test_can_create_boolean_resource_with_false_value()
    {
        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/booleans', [
                            'active' => false,
                        ]);

        $response->assertStatus(201);

        $boolean = Boolean::first();
        $this->assertEquals('No', $boolean->active);
    }
}
