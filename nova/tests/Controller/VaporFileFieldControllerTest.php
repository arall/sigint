<?php

namespace Laravel\Nova\Tests\Controller;

use Faker\Provider\Uuid;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Laravel\Nova\Tests\Fixtures\VaporFile;
use Laravel\Nova\Tests\IntegrationTest;
use Symfony\Component\HttpFoundation\StreamedResponse;

class VaporFileFieldControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_can_store_a_file()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();

        $response = $this->withoutExceptionHandling()
            ->postJson('/nova-api/vapor-files', [
                'avatar' => 'avatar.jpg',
                'vaporFile' => [
                    'key' => 'tmp/'.$uuid,
                    'uuid' => $uuid,
                ],
            ]);

        $response->assertStatus(201);

        Storage::disk('s3')->assertExists($uuid);

        $file = VaporFile::first();

        $this->assertEquals($uuid, $file->avatar);
    }

    public function test_can_store_a_file_with_extra_fields()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();

        $response = $this->withoutExceptionHandling()
            ->postJson('/nova-api/vapor-files', [
                'avatar' => 'avatar.jpg',
                'vaporFile' => [
                    'key' => 'tmp/'.$uuid,
                    'uuid' => $uuid,
                ],
            ]);

        $response->assertStatus(201);

        Storage::disk('s3')->assertExists($uuid);

        $file = VaporFile::first();

        $this->assertEquals($uuid, $file->avatar);
        $this->assertEquals('avatar.jpg', $file->original_name);
    }

    public function test_update_prunable_file()
    {
        $this->setupVaporFilesystem();
        $oldUuid = $this->simulateUploadToVapor();

        // Save the resource with that image
        $this->withoutExceptionHandling()
            ->postJson('/nova-api/vapor-files', [
                'avatar' => 'avatar.jpg',
                'vaporFile' => [
                    'key' => 'tmp/'.$oldUuid,
                ],
            ])->assertStatus(201);

        // Assert image exists
        $oldFile = VaporFile::first();
        Storage::disk('s3')->assertExists($oldFile->avatar);

        // Simulate new image uploaded to Vapor
        $newUuid = $this->simulateUploadToVapor();

        // Save the existing resource with that image
        $this->withoutExceptionHandling()
            ->putJson('/nova-api/vapor-files/'.$oldFile->id, [
                'avatar' => 'new_avatar.jpg',
                'vaporFile' => [
                    'key' => 'tmp/'.$newUuid,
                ],
            ]);

        $file = $oldFile->fresh();

        Storage::disk('s3')->assertMissing($oldUuid);
        Storage::disk('s3')->assertExists($file->avatar);
        $this->assertEquals($newUuid, $file->avatar);
        $this->assertEquals('new_avatar.jpg', $file->original_name);
    }

//    public function test_update_prunable_file_with_custom_delete_callback()
//    {
//        $_SERVER['nova.fileResource.imageField'] = function () {
//            return Image::make('Avatar', 'avatar')
//                ->prunable()
//                ->delete(function ($request, $model, $disk, $path) {
//                    Storage::disk($disk)->delete($path);
//                });
//        };
//
//        $response = $this->withExceptionHandling()
//            ->postJson('/nova-api/files', [
//                'avatar' => UploadedFile::fake()->image('avatar.png'),
//            ]);
//
//        $response->assertStatus(201);
//
//        $_SERVER['__nova.fileResource.imageName'] = 'avatar2.png';
//
//        $file = File::first();
//
//        $filename = $file->avatar;
//        Storage::disk('public')->assertExists($file->avatar);
//
//        $this->withExceptionHandling()
//            ->postJson('/nova-api/files/'.$file->id, [
//                '_method'=>'PUT',
//                'avatar' => UploadedFile::fake()->image('avatar2.png'),
//            ]);
//
//        unset($_SERVER['nova.fileResource.imageField']);
//
//        $file = File::first();
//
//        Storage::disk('public')->assertMissing($filename);
//        Storage::disk('public')->assertExists($file->avatar);
//        $this->assertnotEquals($filename, $file->avatar);
//    }
//
    public function test_proper_response_returned_when_required_file_not_provided()
    {
        $this->setupVaporFilesystem();
        $_SERVER['nova.vaporFile.required'] = true;

        $response = $this->withExceptionHandling()
                        ->postJson('/nova-api/vapor-files', [
                            'avatar' => null,
                        ]);

        $response->assertStatus(422);
        $this->assertEmpty(Storage::disk('s3')->allFiles());
    }

    public function test_file_field_returns_proper_meta_data()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();
        $this->saveVaporFile($uuid);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/vapor-files/'.VaporFile::first()->id);

        $response->assertStatus(200);
        $file = $response->original['resource']['fields'][1]->jsonSerialize();
        $this->assertTrue($file['downloadable']);
        $this->assertEquals('http://mycdn.com/image/'.$uuid, $file['thumbnailUrl']);
    }

    public function test_file_can_be_downloaded()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();
        $this->saveVaporFile($uuid);

        $response = $this->withExceptionHandling()
                        ->get('/nova-api/vapor-files/'.VaporFile::first()->id.'/download/avatar');

        $response->assertStatus(200);
        $this->assertInstanceOf(StreamedResponse::class, $response->baseResponse);
    }

    public function test_file_field_can_be_deleted_and_extra_columns_are_nulled()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();
        $this->saveVaporFile($uuid);

        $response = $this->withoutExceptionHandling()
                        ->deleteJson('/nova-api/vapor-files/'.VaporFile::first()->id.'/field/avatar');

        $response->assertStatus(200);
        $this->assertCount(2, VaporFile::first()->actions);

        $file = VaporFile::first();
        $this->assertNull($file->avatar);
        $this->assertNull($file->original_name);
    }

    public function test_file_fields_are_deleted_when_resource_is_deleted()
    {
        $this->setupVaporFilesystem();
        $uuid = $this->simulateUploadToVapor();
        $this->saveVaporFile($uuid);

        $response = $this->withoutExceptionHandling()
                        ->deleteJson('/nova-api/vapor-files', [
                            'resources' => [VaporFile::first()->id],
                        ]);

        $response->assertStatus(200);
        $this->assertEquals(0, VaporFile::count());
    }

    protected function setupVaporFilesystem()
    {
        Storage::fake('s3');
        config(['filesystems.default' => 's3']);
        config()->offsetUnset('filesystems.disks.local');
        config()->offsetUnset('filesystems.disks.public');
    }

    protected function simulateUploadToVapor()
    {
        $uuid = Uuid::uuid();

        $file = UploadedFile::fake()->image(Str::random(16));
        $file->storeAs('tmp', $uuid, 's3');

        Storage::disk('s3')->assertExists('tmp/'.$uuid);

        return $uuid;
    }

    protected function saveVaporFile($uuid)
    {
        $response = $this->withExceptionHandling()
            ->postJson('/nova-api/vapor-files', [
                'avatar' => 'avatar.jpg',
                'vaporFile' => [
                    'key' => 'tmp/'.$uuid,
                ],
            ]);

        $this->assertNotNull(VaporFile::first());

        return $response;
    }
}
