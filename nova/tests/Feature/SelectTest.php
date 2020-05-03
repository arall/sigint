<?php

namespace Laravel\Nova\Tests\Feature;

use DateTimeZone;
use Laravel\Nova\Fields\Select;
use Laravel\Nova\Tests\IntegrationTest;

class SelectTest extends IntegrationTest
{
    public function test_select_fields_resolve_the_correct_values()
    {
        $field = Select::make('Sizes')->options(function () {
            return [
                'L' => 'Large',
                'S' => 'Small',
            ];
        });

        $field->resolve((object) ['size' => 'L'], 'size');
        $this->assertEquals('L', $field->value);

        $field->resolveForDisplay((object) ['size' => 'L'], 'size');
        $this->assertEquals('L', $field->value);
    }

    public function test_select_fields_can_display_options_using_labels()
    {
        $field = Select::make('Sizes')->options([
            'L' => 'Large',
            'S' => 'Small',
        ])->displayUsingLabels();

        $this->assertSubset([
            'options' => [
                [
                    'label' => 'Large',
                    'value' => 'L',
                ],
                [
                    'label' => 'Small',
                    'value' => 'S',
                ],
            ],
        ], $field->jsonSerialize());

        $field->resolve((object) ['size' => 'L'], 'size');
        $this->assertEquals('L', $field->value);

        $field->resolveForDisplay((object) ['size' => 'L'], 'size');
        $this->assertEquals('Large', $field->value);
    }

    public function test_select_fields_can_have_custom_display_callback()
    {
        $field = Select::make('Sizes')->options([
            'L' => 'Large',
            'S' => 'Small',
        ])->displayUsing(function ($value) {
            return 'Wew';
        });

        $field->resolve((object) ['size' => 'L'], 'size');
        $this->assertEquals('L', $field->value);

        $field->resolveForDisplay((object) ['size' => 'L'], 'size');
        $this->assertEquals('Wew', $field->value);
    }

    public function test_select_fields_can_use_callable_array_as_options()
    {
        $field = Select::make('Sizes')->options(['DateTimeZone', 'listIdentifiers']);

        $expected = collect(DateTimeZone::listIdentifiers())->map(function ($tz, $key) {
            return ['label' => $tz, 'value' => $key];
        })->all();

        $this->assertSubset(['options' => $expected], $field->jsonSerialize());

        $field->resolve((object) ['timezone' => 'America/Chicago'], 'timezone');
        $this->assertEquals('America/Chicago', $field->value);

        $field->resolveForDisplay((object) ['timezone' => 'America/Chicago'], 'timezone');
        $this->assertEquals('America/Chicago', $field->value);
    }

    public function test_select_fields_using_non_callable_array_with_two_items()
    {
        $field = Select::make('Sizes')->options(['Nova', 'site']);

        $this->assertSubset([
            'options' => [
                [
                    'label' => 'Nova',
                    'value' => 0,
                ],
                [
                    'label' => 'site',
                    'value' => 1,
                ],
            ],
        ], $field->jsonSerialize());
    }

    public function test_select_fields_can_accept_closures_as_options()
    {
        $field = Select::make('Sizes')->options(function () {
            return [
                'L' => 'Large',
                'S' => 'Small',
            ];
        })->displayUsingLabels();

        $this->assertSubset([
            'options' => [
                [
                    'label' => 'Large',
                    'value' => 'L',
                ],
                [
                    'label' => 'Small',
                    'value' => 'S',
                ],
            ],
        ], $field->jsonSerialize());
    }

    public function test_select_fields_can_accept_collections_as_options()
    {
        $field = Select::make('Sizes')->options(collect([
            'L' => 'Large',
            'S' => 'Small',
        ]));

        $this->assertSubset([
            'options' => [
                [
                    'label' => 'Large',
                    'value' => 'L',
                ],
                [
                    'label' => 'Small',
                    'value' => 'S',
                ],
            ],
        ], $field->jsonSerialize());
    }

    public function test_select_fields_can_accept_non_associative_collections_as_options()
    {
        $field = Select::make('Sizes')->options(collect(['L', 'S']));

        $this->assertSubset([
            'options' => [
                [
                    'label' => 'L',
                    'value' => 0,
                ],
                [
                    'label' => 'S',
                    'value' => 1,
                ],
            ],
        ], $field->jsonSerialize());
    }
}
