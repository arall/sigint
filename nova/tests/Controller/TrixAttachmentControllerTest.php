<?php

namespace Laravel\Nova\Tests\Controller;

use Faker\Provider\Uuid;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\DB;
use Laravel\Nova\Tests\Fixtures\Discussion;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;
use Laravel\Nova\Trix\Attachment;
use Laravel\Nova\Trix\PendingAttachment;

class TrixAttachmentControllerTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();

        $this->authenticate();
    }

    public function test_adding_trix_attachments_to_fields()
    {
        $user = factory(User::class)->create();
        $draftId = Uuid::uuid();

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions/trix-attachment/body', [
                'draftId' => $draftId,
                'attachment' => UploadedFile::fake()->image('avatar.png'),
                'Content-Type' => 'image/png',
            ])->assertOk();

        $this->assertCount(1, PendingAttachment::all());

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions', [
                'user' => $user->id,
                'title' => 'Really cool discussion',
                'body' => 'This is the content of the discussion',
                'bodyDraftId' => $draftId,
            ])->assertStatus(201);

        tap(Discussion::first(), function ($discussion) {
            $this->assertCount(0, DB::table('nova_pending_trix_attachments')->get());

            $this->assertDatabaseHas('nova_trix_attachments', [
                'attachable_type' => Discussion::class,
                'attachable_id' => $discussion->id,
                'disk' => 'public',
            ]);

            tap(Attachment::first(), function ($attachment) {
                $this->assertNotNull($attachment->attachment);
                $this->assertStringContainsString('storage', $attachment->url);
            });
        });
    }

    public function test_removing_trix_attachments()
    {
        $user = factory(User::class)->create();
        $draftId = Uuid::uuid();

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions/trix-attachment/body', [
                'draftId' => $draftId,
                'attachment' => UploadedFile::fake()->image('avatar.png'),
                'Content-Type' => 'image/png',
            ])->assertOk();

        $this->assertCount(1, PendingAttachment::all());

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions', [
                'user' => $user->id,
                'title' => 'Really cool discussion',
                'body' => 'This is the content of the discussion',
                'bodyDraftId' => $draftId,
            ])->assertStatus(201);

        tap(Attachment::first(), function ($attachment) {
            $this->withoutExceptionHandling()
                ->deleteJson('/nova-api/discussions/trix-attachment/body', [
                    'attachmentUrl' => $attachment->url,
                ])
                ->assertOk();

            $this->assertCount(0, Attachment::get());
        });
    }

    public function test_deleting_resource_with_trix_field_deletes_attachments()
    {
        $user = factory(User::class)->create();
        $draftId = Uuid::uuid();

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions/trix-attachment/body', [
                'draftId' => $draftId,
                'attachment' => UploadedFile::fake()->image('avatar.png'),
                'Content-Type' => 'image/png',
            ])->assertOk();

        $this->assertCount(1, PendingAttachment::all());

        $this->withoutExceptionHandling()
            ->postJson('/nova-api/discussions', [
                'user' => $user->id,
                'title' => 'Really cool discussion',
                'body' => 'This is the content of the discussion',
                'bodyDraftId' => $draftId,
            ])->assertStatus(201);

        tap(Discussion::first(), function ($discussion) {
            $this->withoutExceptionHandling()
                ->deleteJson('/nova-api/discussions', ['resources' => [$discussion->id]])
                ->assertOk();

            $this->assertCount(0, Attachment::get());
        });
    }
}
