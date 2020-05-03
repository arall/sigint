<?php

namespace Laravel\Nova\Tests\Controller;

use Laravel\Nova\Tests\IntegrationTest;

class SqliteSearchControllerTest extends IntegrationTest
{
    use SearchControllerTests;

    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }
}
