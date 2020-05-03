<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Database\Eloquent\Model;
use Laravel\Nova\Fields\Trix;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\IntegrationTest;

class TrixTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_fields_can_execute_custom_filling_callback()
    {
        $field = Trix::make('Trix key')->fillUsing(
            function (
                NovaRequest $request,
                Model $model,
                string $attribute,
                string $requestAttribute
            ) {
                return function () use ($request, $model, $attribute, $requestAttribute) {
                    $this->assertInstanceOf(Post::class, $model);
                    $this->assertEquals('trix_key', $attribute);
                    $this->assertEquals('trix_key', $requestAttribute);
                    $this->assertEquals('TRIX_DATA', $request->{$attribute});
                };
            }
        );

        $model = new Post();
        $result = $field->fill(NovaRequest::create('/?trix_key=TRIX_DATA'), $model);

        $this->assertIsCallable($result);

        $result();
    }
}
