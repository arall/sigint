<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\Sparkline;
use Laravel\Nova\Tests\IntegrationTest;

class SparklineTest extends IntegrationTest
{
    public function test_can_change_chart_style()
    {
        $field = Sparkline::make('Values')->data([
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0,
        ])->asBarChart();

        $field->resolve(null);
        $this->assertEquals('Bar', $field->chartStyle);
    }
}
