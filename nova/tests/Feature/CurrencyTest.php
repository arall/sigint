<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\Currency;
use Laravel\Nova\Tests\IntegrationTest;

class CurrencyTest extends IntegrationTest
{
    public function test_computed_currency_field_can_be_resolved_for_display()
    {
        $field = Currency::make('Cost', function () {
            return 777;
        });

        $field->resolveForDisplay((object) []);

        $this->assertEquals('$777.00', $field->value);
    }

    public function test_the_field_is_displayed_with_currency_character()
    {
        $field = Currency::make('Cost');

        $field->resolveForDisplay((object) ['cost' => 200]);

        $this->assertEquals('$200.00', $field->value);
    }

    public function test_the_field_can_set_currency()
    {
        $field = Currency::make('Cost')->currency('GBP');

        $field->resolveForDisplay((object) ['cost' => 200]);

        $this->assertEquals('£200.00', $field->value);
    }

    public function test_the_field_can_change_locale()
    {
        $field = Currency::make('Cost')->currency('EUR')->locale('nl_NL');

        $field->resolveForDisplay((object) ['cost' => 200]);

        $this->assertEquals('€ 200,00', $field->value);
    }

    public function test_the_field_can_use_minor_units()
    {
        $field = Currency::make('Cost')->asMinorUnits();

        $field->resolve((object) ['cost' => 200]);
        $this->assertEquals(200, $field->value);

        $field->resolveForDisplay((object) ['cost' => 200]);
        $this->assertEquals('$2.00', $field->value);
    }
}
