<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\Badge;
use Laravel\Nova\Tests\IntegrationTest;

class BadgeTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_badge_resolves_correct_value_and_display_class()
    {
        $field = Badge::make('Status');

        $field->resolve((object) ['status' => 'danger']);

        $result = $field->jsonSerialize();

        $this->assertEquals('danger', $result['value']);
        $this->assertEquals('bg-danger-light text-danger-dark', $result['typeClass']);
        $this->assertEquals('danger', $result['label']);
    }

    public function test_computed_badge_resolves_correct_value_and_display_class()
    {
        $field = Badge::make('Status', function () {
            return 'info';
        });

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('info', $field->value);
        $this->assertEquals('bg-info-light text-info-dark', $result['typeClass']);
        $this->assertEquals('info', $result['label']);
    }

    public function test_computed_badge_with_custom_map_resolves_correct_value_and_display_class()
    {
        $field = Badge::make('Status', function () {
            return 'draft';
        })->map([
            'draft' => 'danger',
            'published' => 'success',
        ]);

        $field->resolveForDisplay((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('draft', $field->value);
        $this->assertEquals('bg-danger-light text-danger-dark', $result['typeClass']);
        $this->assertEquals('draft', $result['label']);
    }

    public function test_badge_with_custom_class_map_returns_correct_class()
    {
        $field = Badge::make('Status')->map([
            'draft' => 'info',
            'published' => 'success',
        ]);

        $field->resolve((object) ['status' => 'published']);

        $result = $field->jsonSerialize();

        $this->assertEquals('published', $field->value);
        $this->assertEquals('bg-success-light text-success-dark', $result['typeClass']);
        $this->assertEquals('published', $result['label']);
    }

    public function test_computed_badge_with_custom_class_map_returns_correct_class()
    {
        $field = Badge::make('Status', function () {
            return 'draft';
        })->map([
            'draft' => 'warning',
            'published' => 'success',
        ]);

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('draft', $field->value);
        $this->assertEquals('bg-warning-light text-warning-dark', $result['typeClass']);
        $this->assertEquals('draft', $result['label']);
    }

    public function test_badge_can_be_customized_with_custom_css_classes()
    {
        $field = Badge::make('Status', function () {
            return 'draft';
        })->types([
            'draft' => 'custom class names',
        ]);

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('draft', $field->value);
        $this->assertEquals('custom class names', $result['typeClass']);
    }

    public function test_badge_can_be_customized_with_custom_css_classes_as_array()
    {
        $field = Badge::make('Status', function () {
            return 'draft';
        })->types([
            'draft' => ['custom', 'class', 'names'],
        ]);

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('draft', $field->value);
        $this->assertEquals(['custom', 'class', 'names'], $result['typeClass']);
    }

    public function test_badge_has_built_in_display_classes_when_adding_a_custom_type()
    {
        $field = Badge::make('Status', function () {
            return 'success';
        })->addTypes([
            'draft' => 'custom class names',
        ]);

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('success', $field->value);
        $this->assertEquals('bg-success-light text-success-dark', $result['typeClass']);
    }

    public function test_badge_built_in_type_can_be_overridden()
    {
        $field = Badge::make('Status', function () {
            return 'success';
        })->addTypes([
            'success' => 'custom class names',
        ]);

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('success', $field->value);
        $this->assertEquals('custom class names', $result['typeClass']);
    }

    public function test_badge_can_set_custom_labels()
    {
        $field = Badge::make('Status')->labels([
            'info' => 'Active',
            'danger' => 'Refunded',
        ]);

        $field->resolve((object) ['status' => 'danger']);

        $result = $field->jsonSerialize();

        $this->assertEquals('Refunded', $result['label']);
    }

    public function test_badge_with_custom_mapping_and_labels()
    {
        $field = Badge::make('Status')->map([
            true => 'success',
            false => 'danger',
        ])->labels([
            true => 'Yes',
            false => 'No',
        ]);

        $field->resolve((object) ['status' => true]);

        $result = $field->jsonSerialize();

        $this->assertEquals('Yes', $result['label']);

        $field->resolve((object) ['status' => false]);

        $result = $field->jsonSerialize();

        $this->assertEquals('No', $result['label']);
    }

    public function test_badge_can_use_a_custom_label()
    {
        $field = Badge::make('Status', function () {
            return 'danger';
        })->label(function ($value) {
            return 'Custom: '.$value;
        });

        $field->resolve((object) []);

        $result = $field->jsonSerialize();

        $this->assertEquals('danger', $field->value);
        $this->assertEquals('bg-danger-light text-danger-dark', $result['typeClass']);
        $this->assertEquals('Custom: danger', $result['label']);
    }
}
