<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\IntegrationTest;

class NullableTest extends IntegrationTest
{
    public function test_nullable_can_be_null()
    {
        $field = Text::make('Text')->nullable()->nullValues(['', 0]);

        $model = new \stdClass();

        $field->fill(NovaRequest::create('/?text='), $model);

        $this->assertNull($model->text);

        $field->fill(NovaRequest::create('/?text=1'), $model);

        $this->assertEquals('1', $model->text);

        $field->fill(NovaRequest::create('/?text=0'), $model);

        $this->assertNull($model->text);
    }

    public function test_nullable_with_callback()
    {
        $field = Text::make('Text')->nullable()->nullValues(function ($value) {
            return $value == '0';
        });

        $model = new \stdClass();

        $field->fill(NovaRequest::create('/?text='), $model);

        $this->assertEquals('', $model->text);

        $field->fill(NovaRequest::create('/?text=0'), $model);

        $this->assertNull($model->text);
    }
}
