<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Support\Collection;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Http\Requests\ResourceDetailRequest;
use Laravel\Nova\Http\Requests\ResourceIndexRequest;
use Laravel\Nova\Tests\Fixtures\Post;
use Laravel\Nova\Tests\Fixtures\PostResource;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\Fixtures\UserWithCustomFields;
use Laravel\Nova\Tests\IntegrationTest;

class ResourceFieldTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_can_resolve_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertInstanceOf(Collection::class, $resource->availableFields($request));
    }

    public function test_can_resolve_fields_with_empty_model()
    {
        $user = new User;
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertInstanceOf(Collection::class, $resource->availableFields($request));
    }

    public function test_missing_fields_are_removed()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(1, $resource->availableFields($request)->where('attribute', 'id'));
        $this->assertCount(0, $resource->availableFields($request)->where('attribute', 'test'));
    }

    public function test_id_is_automatically_added_when_serializing()
    {
        $post = factory(Post::class)->create();

        $resource = new PostResource($post);
        $request = NovaRequest::create('/');

        $this->assertNull($resource->availableFields($request)->where('attribute', 'id')->first());
        $this->assertEquals($post->id, $resource->serializeForIndex($request)['id']->value);
    }

    public function test_index_only_fields_are_respected()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(1, $resource->indexFields($request)->where('attribute', 'index'));
        $this->assertCount(0, $resource->creationFields($request)->where('attribute', 'index'));
        $this->assertCount(0, $resource->updateFields($request)->where('attribute', 'index'));
        $this->assertCount(0, $resource->detailFields($request)->where('attribute', 'index'));
    }

    public function test_detail_only_fields_are_respected()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(0, $resource->indexFields($request)->where('attribute', 'detail'));
        $this->assertCount(0, $resource->creationFields($request)->where('attribute', 'detail'));
        $this->assertCount(0, $resource->updateFields($request)->where('attribute', 'detail'));
        $this->assertCount(1, $resource->detailFields($request)->where('attribute', 'detail'));
    }

    public function test_form_only_fields_are_respected()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(0, $resource->indexFields($request)->where('attribute', 'form'));
        $this->assertCount(1, $resource->creationFields($request)->where('attribute', 'form'));
        $this->assertCount(1, $resource->updateFields($request)->where('attribute', 'form'));
        $this->assertCount(0, $resource->detailFields($request)->where('attribute', 'form'));
    }

    public function test_relationships_are_available_when_appropriate()
    {
        // Has Many...
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(0, $resource->indexFields($request)->where('attribute', 'posts'));
        $this->assertCount(0, $resource->creationFields($request)->where('attribute', 'posts'));
        $this->assertCount(0, $resource->updateFields($request)->where('attribute', 'posts'));
        $this->assertCount(1, $resource->detailFields($request)->where('attribute', 'posts'));

        // Belongs To...
        $user = factory(Post::class)->create();
        $resource = new PostResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(1, $resource->indexFields($request)->where('attribute', 'user'));
        $this->assertCount(1, $resource->creationFields($request)->where('attribute', 'user'));
        $this->assertCount(1, $resource->updateFields($request)->where('attribute', 'user'));
        $this->assertCount(1, $resource->detailFields($request)->where('attribute', 'user'));
    }

    public function test_computed_fields_are_not_available_on_forms()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = NovaRequest::create('/');

        $this->assertCount(2, $resource->indexFields($request)->where('attribute', 'ComputedField'));
        $this->assertCount(0, $resource->creationFields($request)->where('attribute', 'ComputedField'));
        $this->assertCount(0, $resource->updateFields($request)->where('attribute', 'ComputedField'));
        $this->assertCount(2, $resource->detailFields($request)->where('attribute', 'ComputedField'));
    }

    public function test_uses_default_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserResource($user);
        $request = ResourceIndexRequest::create('/');

        $this->assertCount(20, $resource->availableFields($request));
    }

    public function test_uses_index_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserWithCustomFields($user);

        $request = ResourceIndexRequest::create('/');

        $this->assertCount(1, $resource->availableFields($request));
        $this->assertEquals('Index Name', $resource->availableFields($request)->first()->name);
    }

    public function test_uses_detail_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserWithCustomFields($user);

        $request = ResourceDetailRequest::create('/');

        $this->assertCount(1, $resource->availableFields($request));
        $this->assertEquals('Detail Name', $resource->availableFields($request)->first()->name);
    }

    public function test_uses_update_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserWithCustomFields($user);

        $request = NovaRequest::create('/', 'GET', [
            'editing' => true,
            'editMode' => 'update',
        ]);

        $this->assertCount(1, $resource->availableFields($request));
        $this->assertEquals('Update Name', $resource->availableFields($request)->first()->name);
    }

    public function test_uses_create_fields()
    {
        $user = factory(User::class)->create();
        $resource = new UserWithCustomFields($user);

        $request = NovaRequest::create('/', 'GET', [
            'editing' => true,
            'editMode' => 'create',
        ]);

        $this->assertCount(2, $resource->availableFields($request));
        $this->assertEquals('Create Name', $resource->availableFields($request)->first()->name);
    }
}
