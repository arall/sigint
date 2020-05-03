<?php

namespace Laravel\Nova\Tests\Feature;

use Illuminate\Http\Request;
use Illuminate\Routing\Route;
use Laravel\Nova\Fields\Avatar;
use Laravel\Nova\Fields\BelongsTo;
use Laravel\Nova\Fields\MorphTo;
use Laravel\Nova\Fields\Password;
use Laravel\Nova\Fields\Select;
use Laravel\Nova\Fields\Text;
use Laravel\Nova\Fields\Textarea;
use Laravel\Nova\Fields\Trix;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Tests\Fixtures\File;
use Laravel\Nova\Tests\Fixtures\FileResource;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\IntegrationTest;
use stdClass;

class FieldTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_component_can_be_customized()
    {
        Text::useComponent('something');
        $this->assertEquals('something', (new Text('Foo', 'foo'))->component());

        $this->assertEquals('belongs-to-field', (new BelongsTo('User', 'user', UserResource::class))->component());
    }

    public function test_fields_can_have_custom_display_callback()
    {
        $field = Text::make('Name')->displayUsing(function ($value) {
            return strtoupper($value);
        });

        $field->resolve((object) ['name' => 'Taylor'], 'name');
        $this->assertEquals('Taylor', $field->value);

        $field->resolveForDisplay((object) ['name' => 'Taylor'], 'name');
        $this->assertEquals('TAYLOR', $field->value);
    }

    public function test_fields_can_have_custom_resolver_callback()
    {
        $field = Text::make('Name')->resolveUsing(function ($value, $model, $attribute) {
            return strtoupper($value);
        });

        $field->resolve((object) ['name' => 'Taylor'], 'name');

        $this->assertEquals('TAYLOR', $field->value);
    }

    public function test_fields_can_have_custom_resolver_callback_even_if_field_is_missing()
    {
        $field = Text::make('Name')->resolveUsing(function ($value, $model, $attribute) {
            return strtoupper('default');
        });

        $field->resolve((object) ['name' => 'Taylor'], 'email');

        $this->assertEquals('DEFAULT', $field->value);
    }

    public function test_computed_fields_resolve()
    {
        $field = Text::make('InvokableComputed', function () {
            return 'Computed';
        });

        $field->resolve((object) []);
        $this->assertEquals('Computed', $field->value);
    }

    public function test_computed_fields_resolve_for_display()
    {
        $field = Text::make('InvokableComputed', function ($resource) {
            return 'Computed';
        });

        $field->resolveForDisplay((object) []);
        $this->assertEquals('Computed', $field->value);
    }

    public function test_computed_fields_use_display_callback()
    {
        $field = Text::make('InvokableComputed', function ($resource) {
            return 'Computed';
        })->displayUsing(function ($value) {
            return sprintf('Displayed Via %s Field', $value);
        });

        $field->resolveForDisplay((object) []);
        $this->assertEquals('Displayed Via Computed Field', $field->value);
    }

    public function test_computed_fields_resolve_with_resource()
    {
        $field = Text::make('InvokableComputed', function ($resource) {
            return $resource->value;
        });

        $field->resolve((object) ['value' => 'Computed']);
        $this->assertEquals('Computed', $field->value);
    }

    public function test_computed_fields_resolve_for_display_with_resource()
    {
        $field = Text::make('InvokableComputed', function ($resource) {
            return $resource->value;
        });

        $field->resolveForDisplay((object) ['value' => 'Other value']);
        $this->assertEquals('Other value', $field->value);
    }

    public function test_can_see_when_proxies_to_gate()
    {
        unset($_SERVER['__nova.ability']);

        $field = Text::make('Name')->canSeeWhen('view-profile');
        $callback = $field->seeCallback;

        $request = Request::create('/', 'GET');

        $request->setUserResolver(function () {
            return new class {
                public function can($ability, $arguments = [])
                {
                    $_SERVER['__nova.ability'] = $ability;

                    return true;
                }
            };
        });

        $this->assertTrue($callback($request));
        $this->assertEquals('view-profile', $_SERVER['__nova.ability']);
    }

    public function test_textarea_fields_dont_show_their_content_by_default()
    {
        $textarea = Textarea::make('Name');
        $trix = Trix::make('Name');
        $markdown = Trix::make('Name');

        $this->assertFalse($textarea->shouldBeExpanded());
        $this->assertFalse($trix->shouldBeExpanded());
        $this->assertFalse($markdown->shouldBeExpanded());
    }

    public function test_textarea_fields_can_be_set_to_always_show_their_content()
    {
        $textarea = Textarea::make('Name')->alwaysShow();
        $trix = Trix::make('Name')->alwaysShow();
        $markdown = Trix::make('Name')->alwaysShow();

        $this->assertTrue($textarea->shouldBeExpanded());
        $this->assertTrue($trix->shouldBeExpanded());
        $this->assertTrue($markdown->shouldBeExpanded());
    }

    public function test_textarea_fields_can_have_custom_should_show_callback()
    {
        $callback = function () {
            return true;
        };

        $textarea = Textarea::make('Name')->shouldShow($callback);
        $trix = Trix::make('Name')->shouldShow($callback);
        $markdown = Trix::make('Name')->shouldShow($callback);

        $this->assertTrue($textarea->shouldBeExpanded());
        $this->assertTrue($trix->shouldBeExpanded());
        $this->assertTrue($markdown->shouldBeExpanded());
    }

    public function test_text_fields_can_be_serialized()
    {
        $field = Text::make('Name');

        $this->assertContains([
            'component' => 'text-field',
            'prefixComponent' => true,
            'indexName' => 'Name',
            'name' => 'Name',
            'attribute' => 'name',
            'value' => null,
            'panel' => null,
            'sortable' => false,
            'textAlign' => 'left',
        ], $field->jsonSerialize());
    }

    public function test_text_fields_can_have_an_array_of_suggestions()
    {
        $field = Text::make('Name')->suggestions([
            'Taylor',
            'David',
            'Mohammed',
            'Dries',
            'James',
        ]);

        $this->assertContains([
            'suggestions' => ['James'],
        ], $field->jsonSerialize());
    }

    public function test_text_fields_can_have_suggestions_from_a_closure()
    {
        $field = Text::make('Name')->suggestions(function () {
            return [
                'Taylor',
                'David',
                'Mohammed',
                'Dries',
                'James',
            ];
        });

        $this->assertContains([
            'suggestions' => ['James'],
        ], $field->jsonSerialize());
    }

    public function test_text_fields_can_use_callable_array_as_suggestions()
    {
        $field = Text::make('Sizes')->suggestions(['Laravel\Nova\Tests\Feature\SuggestionOptions', 'options']);

        $this->assertContains([
            'suggestions' => [
                'Taylor',
                'David',
                'Mohammed',
                'Dries',
                'James',
            ],
        ], $field->jsonSerialize());
    }

    public function test_text_fields_can_have_extra_meta_data()
    {
        $field = Text::make('Name')->withMeta(['extraAttributes' => [
            'placeholder' => 'This is a placeholder',
        ]]);

        $this->assertContains([
            'extraAttributes' => ['placeholder' => 'This is a placeholder'],
        ], $field->jsonSerialize());
    }

    public function test_select_fields_options_with_additional_parameters()
    {
        $expected = [
            ['label' => 'A', 'value' => 'a'],
            ['label' => 'B', 'value' => 'b'],
            ['label' => 'C', 'value' => 'c'],
            ['label' => 'D', 'value' => 'd', 'group' => 'E'],
        ];
        $field = Select::make('Name')->options([
            'a' => 'A',
            'b' => ['label' => 'B'],
            ['value' => 'c', 'label' => 'C'],
            ['value' => 'd', 'label' => 'D', 'group' => 'E'],
        ]);

        $this->assertJsonStringEqualsJsonString(json_encode($expected), json_encode($field->jsonSerialize()['options']));
    }

    public function test_field_can_be_set_to_readonly()
    {
        $field = Text::make('Avatar');
        $field->readonly(true);

        $this->assertTrue($field->isReadonly(NovaRequest::create('/', 'get')));
    }

    public function test_field_can_be_set_to_readonly_using_a_callback()
    {
        $field = Text::make('Avatar');
        $field->readonly(function () {
            return true;
        });

        $this->assertTrue($field->isReadonly(NovaRequest::create('/', 'get')));
    }

    public function test_field_can_be_set_to_not_be_readonly_using_a_callback()
    {
        $field = Text::make('Avatar');
        $field->readonly(function () {
            return false;
        });

        $this->assertFalse($field->isReadonly(NovaRequest::create('/', 'get')));
    }

    public function test_can_set_field_to_readonly_on_create_requests()
    {
        $request = NovaRequest::create('/nova-api/users', 'POST', [
            'editing' => true,
            'editMode' => 'create',
        ]);

        $field = Text::make('Name')->readonly(function ($request) {
            return $request->isCreateOrAttachRequest();
        });

        $this->assertTrue($field->isReadonly($request));
    }

    public function test_can_set_field_to_readonly_on_update_requests()
    {
        $request = NovaRequest::create('/nova-api/users/1', 'PUT', [
            'editing' => true,
            'editMode' => 'update',
        ]);

        $field = Text::make('Name')->readonly(function ($request) {
            return $request->isUpdateOrUpdateAttachedRequest();
        });

        $this->assertTrue($field->isReadonly($request));
    }

    public function test_collision_of_request_properties()
    {
        $request = new NovaRequest([], [
            'query' => '',
            'resource' => 'resource',
        ]);

        $request->setMethod('POST');
        $request->setRouteResolver(function () use ($request) {
            return tap(new Route('POST', '/{resource}', function () {
            }), function (Route $route) use ($request) {
                $route->bind($request);
                $route->setParameter('resource', UserResource::class);
            });
        });

        $model = new stdClass();

        Text::make('Resource')->fill($request, $model);
        Password::make('Query')->fill($request, $model);

        $this->assertObjectNotHasAttribute('query', $model);
        $this->assertEquals('resource', $model->resource);
    }

    public function test_fields_are_not_required_by_default()
    {
        $request = NovaRequest::create('/nova-api/users/creation-fields', 'GET');

        $field = Text::make('Name');

        $this->assertFalse($field->isRequired($request));
    }

    public function test_can_mark_a_field_as_required_for_create_if_in_validation()
    {
        $request = NovaRequest::create('/nova-api/users/creation-fields', 'GET', [
            'editing' => true,
            'editMode' => 'create',
        ]);

        $field = Text::make('Name')->rules('required');

        $this->assertTrue($field->isRequired($request));
    }

    public function test_can_mark_a_field_as_required_for_update_if_in_validation()
    {
        $request = NovaRequest::create('/nova-api/users/update-fields', 'GET', [
            'editing' => true,
            'editMode' => 'update',
        ]);

        $field = Text::make('Name')->rules('required');

        $this->assertTrue($field->isRequired($request));
    }

    public function test_can_mark_a_field_as_required_using_callback()
    {
        $request = NovaRequest::create('/nova-api/users', 'GET');

        $field = Text::make('Name')->required();

        $this->assertTrue($field->isRequired($request));

        $field = Text::make('Name')->required(function () {
            return false;
        });

        $this->assertFalse($field->isRequired($request));
    }

    public function test_resolve_only_cover_field()
    {
        $request = NovaRequest::create('/nova-api/files', 'GET');

        $_SERVER['nova.fileResource.additionalField'] = function () {
            return Text::make('Text', function () {
                throw new \Exception('This field should not be resolved.');
            });
        };

        $_SERVER['nova.fileResource.imageField'] = function () {
            return Avatar::make('Avatar', 'avatar', null);
        };

        $url = (new FileResource(new File(['avatar' => 'avatars/avatar.jpg'])))->resolveAvatarUrl($request);

        $this->assertEquals('/storage/avatars/avatar.jpg', $url);

        unset($_SERVER['nova.fileResource.additionalField'], $_SERVER['nova.fileResource.imageField']);
    }

    public function test_can_mark_a_field_as_stacked_using_boolean()
    {
        $field = Text::make('Avatar');
        $field->stacked(true);

        $this->assertTrue($field->stacked);

        $field->stacked(false);

        $this->assertFalse($field->stacked);
    }

    public function test_belongs_to_field_can_have_custom_callback_to_determine_if_we_should_show_create_relation_button()
    {
        $request = NovaRequest::create('/', 'GET', []);

        $field = BelongsTo::make('User', 'user', UserResource::class);

        $field->showCreateRelationButton(false);
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(true);
        $this->assertTrue($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(function ($request) {
            return false;
        });
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(function ($request) {
            return true;
        });
        $this->assertTrue($field->createRelationShouldBeShown($request));

        $field->hideCreateRelationButton();
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton();
        $this->assertTrue($field->createRelationShouldBeShown($request));
    }

    public function test_morph_to_fields_can_have_custom_callback_to_determine_if_we_should_show_create_relation_button()
    {
        $request = NovaRequest::create('/', 'GET', []);

        $field = MorphTo::make('Commentable', 'commentable');

        $field->showCreateRelationButton(false);
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(true);
        $this->assertTrue($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(function ($request) {
            return false;
        });
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton(function ($request) {
            return true;
        });
        $this->assertTrue($field->createRelationShouldBeShown($request));

        $field->hideCreateRelationButton();
        $this->assertFalse($field->createRelationShouldBeShown($request));

        $field->showCreateRelationButton();
        $this->assertTrue($field->createRelationShouldBeShown($request));
    }

    public function test_fields_can_have_help_text()
    {
        $field = Text::make('Name')->help('Custom help text.');

        $this->assertSubset([
            'helpText' => 'Custom help text.',
        ], $field->jsonSerialize());
    }

    public function test_fields_can_specify_a_default_value_as_callback()
    {
        $field = Text::make('Name')->default(function (NovaRequest $request) {
            return $request->url();
        });

        $this->app->instance(
            NovaRequest::class,
            NovaRequest::create('/', 'GET', [
                'editing' => true,
                'editMode' => 'create',
            ])
        );

        $this->assertSubset([
            'value' => 'http://localhost',
        ], $field->jsonSerialize());
    }

    public function test_fields_can_specify_a_default_value()
    {
        $field = Text::make('Name')->default('David Hemphill');

        $this->app->instance(
            NovaRequest::class,
            NovaRequest::create('/', 'GET', [
                'editing' => true,
                'editMode' => 'create',
            ])
        );

        $this->assertSubset([
            'value' => 'David Hemphill',
        ], $field->jsonSerialize());
    }
}

class SuggestionOptions
{
    public static function options()
    {
        return [
            'Taylor',
            'David',
            'Mohammed',
            'Dries',
            'James',
        ];
    }
}
