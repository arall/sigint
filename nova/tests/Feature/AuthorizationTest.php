<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Nova;
use Laravel\Nova\Tests\IntegrationTest;

class AuthorizationTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_authorization_callback_is_executed()
    {
        Nova::auth(function ($request) {
            return $request;
        });

        $this->assertEquals('Taylor', Nova::check('Taylor'));
    }
}
