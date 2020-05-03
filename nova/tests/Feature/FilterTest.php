<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Http\Request;
use Laravel\Nova\Tests\Fixtures\CreateDateFilter;
use Laravel\Nova\Tests\Fixtures\IdFilter;
use Laravel\Nova\Tests\IntegrationTest;

class FilterTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_component_can_be_customized()
    {
        $this->assertEquals('select-filter', (new IdFilter)->component());
        $this->assertEquals('date-filter', (new CreateDateFilter)->component());
    }

    public function test_can_see_when_proxies_to_gate()
    {
        unset($_SERVER['__nova.ability']);

        $filter = (new IdFilter)->canSeeWhen('view-profile');
        $callback = $filter->seeCallback;

        $request = Request::create('/', 'GET');

        $request->setUserResolver(function () {
            return new class {
                public function can($ability, $arguments = [])
                {
                    $_SERVER['__nova.ability'] = $ability;

                    return true;
                }
            };
        });

        $this->assertTrue($callback($request));
        $this->assertEquals('view-profile', $_SERVER['__nova.ability']);
    }

    public function test_filters_can_be_serialized()
    {
        $filter = new CreateDateFilter;

        $this->assertSubset([
            'class' => get_class($filter),
            'name' => $filter->name(),
            'component' => $filter->component(),
            'options' => [],
            'currentValue' => '',
        ], $filter->jsonSerialize());
    }

    public function test_filters_can_have_extra_meta_data()
    {
        $filter = (new CreateDateFilter)->withMeta([
            'extraAttributes' => ['placeholder' => 'This is a placeholder'],
        ]);

        $this->assertSubset([
            'extraAttributes' => ['placeholder' => 'This is a placeholder'],
        ], $filter->jsonSerialize());
    }
}
