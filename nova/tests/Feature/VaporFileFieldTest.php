<?php

namespace Laravel\Nova\Tests\Feature;

use Faker\Provider\Uuid;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Laravel\Nova\Fields\VaporFile;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\VaporFile as Model;
use Laravel\Nova\Tests\Fixtures\VaporFileResource;
use Laravel\Nova\Tests\IntegrationTest;

class VaporFileFieldTest extends IntegrationTest
{
    protected function makeField($name = 'Avatar', $attribute = 'avatar')
    {
        return VaporFile::make($name, $attribute);
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
                return new VaporFakeDownloadResponse(sprintf('http://mycdn.com/downloads/%s', $model->avatar));
            });

            tap(
                $field->toDownloadResponse(NovaRequest::create('/', 'GET'), new VaporFileResource($resource)),
                function ($instance) {
                    $this->assertInstanceOf(VaporFakeDownloadResponse::class, $instance);
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
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals($uuid, $model->avatar);

        Storage::assertExists($uuid);
    }

    public function test_can_customize_file_name_strategy()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->storeAs(fn () => 'bar');

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals('bar', $model->avatar);

        Storage::assertExists('bar');
    }

    public function test_can_customize_file_path_strategy()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->path('foo');

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals('foo/'.$uuid, $model->avatar);
        Storage::assertExists('foo/'.$uuid);
    }

    public function test_can_store_file_extension()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->storeAs(function ($request) {
            return $request->input('vaporFile')['key'].'.'.$request->input('vaporFile')['extension'];
        });

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
                'extension' => 'jpg',
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals('tmp/'.$uuid.'.jpg', $model->avatar);
        Storage::assertExists('tmp/'.$uuid.'.jpg');
    }

    public function test_can_store_original_filename()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->storeAs(function ($request) {
            return $request->input('vaporFile')['filename'];
        });

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
                'filename' => 'wow.png',
                'extension' => 'jpg',
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals('wow.png', $model->avatar);
        Storage::assertExists('wow.png');
    }

    public function test_can_customize_file_path_and_name_strategy()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
//        $file->path('foo');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->path('foo');
        $field->storeAs(function () {
            return 'wew';
        });

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals('foo/wew', $model->avatar);
        Storage::assertExists('foo/wew');
    }

    public function test_can_correctly_store_extra_columns()
    {
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');

        Storage::fake('s3');
        $uuid = Uuid::uuid();
        $file = UploadedFile::fake()->image('wew.jpg');
        $file->storeAs('tmp', $uuid, 's3');
        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        $model = new Model();
        $field = $this->makeField();
        $field->storeOriginalName('original_name');

        $request = NovaRequest::create('/', 'GET', [
            'avatar' => 'wew.jpg',
            'vaporFile' => [
                'key' => 'tmp/'.$uuid,
            ],
        ]);

        $field->fill($request, $model);

        $this->assertEquals($uuid, $model->avatar);
        $this->assertEquals('wew.jpg', $model->original_name);

        Storage::assertExists($uuid);
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

class VaporFakeDownloadResponse
{
    public $path;

    public function __construct($path)
    {
        $this->path = $path;
    }
}
