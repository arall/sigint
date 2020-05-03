<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Actions\ActionEvent;
use Laravel\Nova\Actions\ActionResource;
use Laravel\Nova\Exceptions\NovaExceptionHandler;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\DiscussionResource;
use Laravel\Nova\Tests\Fixtures\ForbiddenUserResource;
use Laravel\Nova\Tests\Fixtures\NotAvailableForNavigationUserResource;
use Laravel\Nova\Tests\Fixtures\NotSearchableUserResource;
use Laravel\Nova\Tests\Fixtures\TagResource;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;

class NovaTest extends IntegrationTest
{
    public function test_nova_can_use_a_custom_report_callback()
    {
        $_SERVER['nova.exception.error_handled'] = false;

        $this->assertFalse($_SERVER['nova.exception.error_handled']);

        Nova::report(function ($exception) {
            $_SERVER['nova.exception.error_handled'] = true;
        });

        app(NovaExceptionHandler::class)->report(new \Exception('It did not work'));

        $this->assertTrue($_SERVER['nova.exception.error_handled']);

        unset($_SERVER['nova.exception.error_handled']);
    }

    public function test_returns_the_configured_action_resource()
    {
        $this->assertEquals(ActionResource::class, Nova::actionResource());

        config(['nova.actions.resource' => CustomActionResource::class]);

        $this->assertEquals(CustomActionResource::class, Nova::actionResource());
    }

    public function test_returns_the_configured_action_resource_model_instance()
    {
        $this->assertInstanceOf(ActionEvent::class, Nova::actionEvent());

        config(['nova.actions.resource' => CustomActionResource::class]);

        $this->assertInstanceOf(CustomActionEvent::class, Nova::actionEvent());
    }

    public function test_has_default_sidebar_sorting_strategy()
    {
        $callback = function ($resource) {
            return $resource::label();
        };

        $this->assertEquals($callback, Nova::sortResourcesWith());
    }

    public function test_can_specify_user_sortable_closure_for_sorting()
    {
        $callback = function ($resource) {
            return $resource::$priority;
        };

        Nova::sortResourcesBy($callback);

        $this->assertEquals($callback, Nova::$sortCallback);

        Nova::sortResourcesBy(function ($resource) {
            return $resource::label();
        });
    }

    public function test_can_get_available_resources()
    {
        Nova::replaceResources([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
        ]);

        $this->assertEquals([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
        ], Nova::availableResources(NovaRequest::create('/')));
    }

    public function test_only_authorized_resources_are_returned()
    {
        Nova::replaceResources([
            DiscussionResource::class,
            ForbiddenUserResource::class,
        ]);

        $this->assertEquals([
            DiscussionResource::class,
        ], Nova::availableResources(NovaRequest::create('/')));
    }

    public function test_only_available_for_navigation_resources_are_returned()
    {
        Nova::replaceResources([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
            NotAvailableForNavigationUserResource::class,
        ]);

        $this->assertEquals([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
        ], Nova::resourcesForNavigation(NovaRequest::create('/')));
    }

    public function test_only_globally_searchable_resources_are_returned()
    {
        Nova::replaceResources([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
            NotSearchableUserResource::class,
        ]);

        $this->assertEquals([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
        ], Nova::globallySearchableResources(NovaRequest::create('/')));
    }

    public function test_resources_can_be_grouped_for_navigation()
    {
        Nova::replaceResources([
            UserResource::class,
            DiscussionResource::class,
            TagResource::class,
            NotSearchableUserResource::class,
        ]);

        tap(Nova::groupedResourcesForNavigation(NovaRequest::create('/')), function ($resources) {
            $this->assertArrayHasKey('Other', $resources);
            $this->assertArrayHasKey('Content', $resources);

            $this->assertEquals([
                NotSearchableUserResource::class,
                UserResource::class,
            ], $resources['Other']->all());

            $this->assertEquals([
                DiscussionResource::class,
                TagResource::class,
            ], $resources['Content']->all());
        });
    }
}

class CustomActionEvent extends ActionEvent
{
}

class CustomActionResource extends ActionResource
{
    public static $model = CustomActionEvent::class;
}
