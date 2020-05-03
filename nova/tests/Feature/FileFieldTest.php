<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Laravel\Nova\Fields\File;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\VaporFile as Model;
use Laravel\Nova\Tests\Fixtures\VaporFileResource;
use Laravel\Nova\Tests\IntegrationTest;

class FileFieldTest extends IntegrationTest
{
    protected function makeField($name = 'Avatar', $attribute = 'avatar')
    {
        return File::make($name, $attribute);
    }

    protected function createModel()
    {
        return Model::create([
            'avatar' => 'wew.jpg',
        ]);
    }

    protected function assertFixture($callback)
    {
        $model = $this->createModel();

        $field = $this->makeField()
            ->thumbnail(function ($value, $disk, $resource) {
                return sprintf('http://mycdn.com/%s', $resource->avatar);
            })
            ->preview(function ($att, $disk, $resource) {
                return sprintf('http://mycdn.com/previews/%s', $resource->avatar);
            })
            ->delete(function () {
                return 'deleted!';
            })
            ->acceptedTypes('image/*')
            ->prunable();

        $field->resolve($model);

        call_user_func($callback, $field, $model);
    }

    public function test_field_can_accept_a_thumbail_callback()
    {
        $this->assertFixture(function ($field) {
            $this->assertEquals('http://mycdn.com/wew.jpg', $field->jsonSerialize()['thumbnailUrl']);
        });
    }

    public function test_field_can_accept_a_preview_callback()
    {
        $this->assertFixture(function ($field) {
            $this->assertEquals('http://mycdn.com/previews/wew.jpg', $field->jsonSerialize()['previewUrl']);
        });
    }

    public function test_theres_no_thumbnail_by_default()
    {
        tap($this->makeField(), function ($field) {
            $this->assertNull($field->jsonSerialize()['thumbnailUrl']);
        });
    }

    public function test_theres_no_preview_by_default()
    {
        tap($this->makeField(), function ($field) {
            $this->assertNull($field->jsonSerialize()['previewUrl']);
        });
    }

    public function test_it_is_downloadable_by_default()
    {
        tap($this->makeField(), function ($field) {
            $resource = $this->createModel();

            $field->resolve($resource);

            $this->assertTrue($field->jsonSerialize()['downloadable']);
        });
    }

    public function test_downloads_can_be_disabled()
    {
        $this->assertFixture(function ($field, $resource) {
            $field->disableDownload();
            $this->assertFalse($field->jsonSerialize()['downloadable']);
        });
    }

    public function test_download_response_can_be_set()
    {
        $this->assertFixture(function ($field, $resource) {
            $field->download(function ($request, $model) {
                return new FakeDownloadResponse(sprintf('http://mycdn.com/downloads/%s', $model->avatar));
            });

            tap(
                $field->toDownloadResponse(NovaRequest::create('/', 'GET'), new VaporFileResource($resource)),
                function ($instance) {
                    $this->assertInstanceOf(FakeDownloadResponse::class, $instance);
                    $this->assertEquals('http://mycdn.com/downloads/wew.jpg', $instance->path);
                }
            );
        });
    }

    public function test_is_deletable_by_default()
    {
        tap($this->makeField(), function ($field) {
            $this->assertTrue($field->jsonSerialize()['deletable']);
        });
    }

    public function test_delete_strategy_can_be_customized()
    {
        $this->assertFixture(function ($field) {
            $field->deleteCallback == function () {
                return 'deleted!';
            };
        });
    }

    public function test_can_set_the_accepted_file_types()
    {
        $this->assertFixture(function ($field) {
            $this->assertEquals('image/*', $field->acceptedTypes);
        });
    }

    public function test_can_correctly_fill_the_main_attribute_and_store_file()
    {
        Storage::fake();
        Storage::fake('public');

        $model = new Model();
        $field = $this->makeField();
        $field->storeAs(function () {
            return 'david.jpg';
        });

        $request = NovaRequest::create('/', 'GET', [], [], [
            'avatar' => UploadedFile::fake()->image('wew.jpg'),
        ]);

        $field->fill($request, $model);

        $this->assertEquals('david.jpg', $model->avatar);

        Storage::disk('public')->assertExists('david.jpg');
    }

    public function test_field_is_prunable()
    {
        $this->assertFixture(function ($field) {
            $this->assertTrue($field->isPrunable());
            $field->prunable(false);
            $this->assertFalse($field->isPrunable());
        });
    }
}

class FakeDownloadResponse
{
    public $path;

    public function __construct($path)
    {
        $this->path = $path;
    }
}
