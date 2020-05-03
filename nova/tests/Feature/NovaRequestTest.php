<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\IntegrationTest;

class NovaRequestTest extends IntegrationTest
{
    public function test_checking_if_create_request()
    {
        $request = NovaRequest::create('/nova-api/users/1', 'POST', [
            'editing' => true,
            'editMode' => 'create',
        ]);

        $this->assertTrue($request->isCreateOrAttachRequest());
        $this->assertFalse($request->isUpdateOrUpdateAttachedRequest());
    }

    public function test_checking_if_update_request()
    {
        $request = NovaRequest::create('/nova-api/users/1', 'PUT', [
            'editing' => true,
            'editMode' => 'update',
        ]);

        $this->assertTrue($request->isUpdateOrUpdateAttachedRequest());
        $this->assertFalse($request->isCreateOrAttachRequest());
    }
}
