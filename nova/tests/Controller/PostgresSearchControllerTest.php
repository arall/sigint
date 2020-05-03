<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\PostgresIntegrationTest;

class PostgresSearchControllerTest extends PostgresIntegrationTest
{
    use SearchControllerTests;

    public function setUp(): void
    {
        $this->skipIfNotRunning();

        parent::setUp();

        $this->authenticate();
    }
}
