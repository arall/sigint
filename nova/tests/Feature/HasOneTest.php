<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\HasOne;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\Address;
use Laravel\Nova\Tests\Fixtures\AddressResource;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class HasOneTest extends IntegrationTest
{
    public function test_can_determine_if_field_is_not_filled()
    {
        $user = factory(User::class)->create();
        $user2 = factory(User::class)->create();

        $request = NovaRequest::create('/', 'GET', [
            'resourceName' => 'addresses',
            'viaResource' => 'users',
            'viaResourceId' => $user->id,
            'viaRelationship' => 'address',
        ]);

        $address = factory(Address::class)->create(['user_id' => $user2]);

        $field = HasOne::make('Address', 'address', AddressResource::class);

        $this->assertFalse($field->alreadyFilled($request));
    }

    public function test_can_determine_if_field_is_filled()
    {
        $user = factory(User::class)->create();

        $request = NovaRequest::create('/', 'GET', [
            'resourceName' => 'addresses',
            'viaResource' => 'users',
            'viaResourceId' => $user->id,
            'viaRelationship' => 'address',
        ]);

        $address = factory(Address::class)->create(['user_id' => $user]);

        $field = HasOne::make('Address', 'address', AddressResource::class);

        $this->assertTrue($field->alreadyFilled($request));
    }

    public function test_doesnt_fail_with_no_params()
    {
        $user = factory(User::class)->create();

        $request = NovaRequest::create('/', 'GET', []);

        $address = factory(Address::class)->create(['user_id' => $user]);

        $field = HasOne::make('Address', 'address', AddressResource::class);

        $this->assertFalse($field->alreadyFilled($request));
    }
}
