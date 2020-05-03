<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\PostgresIntegrationTest;

/**
 * @group postgres
 */
class PostgresTrendMetricControllerTest extends PostgresIntegrationTest
{
    use TrendDateTests;

    public function setUp(): void
    {
        $this->skipIfNotRunning();

        parent::setUp();

        $this->authenticate();
    }
}
