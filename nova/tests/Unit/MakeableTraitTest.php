<?php

namespace Laravel\Nova\Tests\Unit;

use Laravel\Nova\Makeable;
use Laravel\Nova\Tests\IntegrationTest;

class MakeableTraitTest extends IntegrationTest
{
    public function test_makeable_trait_works()
    {
        $instance = MakeableTest::make('David', 'Tess');

        $this->assertEquals('David', $instance->first);
        $this->assertEquals('Tess', $instance->second);
    }
}

class MakeableTest
{
    use Makeable;

    public $first;
    public $second;

    public function __construct($first, $second)
    {
        $this->first = 'David';
        $this->second = 'Tess';
    }
}
