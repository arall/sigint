<?php

namespace Laravel\Nova\Tests;

use Illuminate\Contracts\Auth\Authenticatable;
use Illuminate\Queue\WorkerOptions;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Schema;
use Laravel\Nova\Nova;
use Laravel\Nova\NovaCoreServiceProvider;
use Laravel\Nova\NovaServiceProvider;
use Laravel\Nova\Tests\Fixtures\AddressResource;
use Laravel\Nova\Tests\Fixtures\BooleanResource;
use Laravel\Nova\Tests\Fixtures\CommentResource;
use Laravel\Nova\Tests\Fixtures\CustomConnectionActionResource;
use Laravel\Nova\Tests\Fixtures\CustomKeyResource;
use Laravel\Nova\Tests\Fixtures\DiscussionResource;
use Laravel\Nova\Tests\Fixtures\FileResource;
use Laravel\Nova\Tests\Fixtures\ForbiddenUserResource;
use Laravel\Nova\Tests\Fixtures\GroupedUserResource;
use Laravel\Nova\Tests\Fixtures\NoopAction;
use Laravel\Nova\Tests\Fixtures\PanelResource;
use Laravel\Nova\Tests\Fixtures\PostResource;
use Laravel\Nova\Tests\Fixtures\ProfileResource;
use Laravel\Nova\Tests\Fixtures\RecipientResource;
use Laravel\Nova\Tests\Fixtures\RoleResource;
use Laravel\Nova\Tests\Fixtures\SoftDeletingFileResource;
use Laravel\Nova\Tests\Fixtures\TagResource;
use Laravel\Nova\Tests\Fixtures\UserResource;
use Laravel\Nova\Tests\Fixtures\UserWithRedirectResource;
use Laravel\Nova\Tests\Fixtures\VaporFileResource;
use Laravel\Nova\Tests\Fixtures\VehicleResource;
use Laravel\Nova\Tests\Fixtures\WheelResource;
use Mockery;
use Orchestra\Testbench\TestCase;

abstract class IntegrationTest extends TestCase
{
    /**
     * The user the request is currently authenticated as.
     *
     * @var mixed
     */
    protected $authenticatedAs;

    /**
     * Setup the test case.
     *
     * @return void
     */
    public function setUp(): void
    {
        parent::setUp();

        Hash::driver('bcrypt')->setRounds(4);

        $this->loadMigrations();

        $this->withFactories(__DIR__.'/Factories');

        Nova::$tools = [];
        Nova::$resources = [];
        NoopAction::$applied = [];
        NoopAction::$appliedToComments = [];

        Nova::resources([
            AddressResource::class,
            BooleanResource::class,
            CommentResource::class,
            CustomKeyResource::class,
            DiscussionResource::class,
            FileResource::class,
            ForbiddenUserResource::class,
            GroupedUserResource::class,
            PanelResource::class,
            PostResource::class,
            ProfileResource::class,
            RecipientResource::class,
            RoleResource::class,
            SoftDeletingFileResource::class,
            TagResource::class,
            UserResource::class,
            UserWithRedirectResource::class,
            VaporFileResource::class,
            VehicleResource::class,
            WheelResource::class,
        ]);

        Nova::auth(function () {
            return true;
        });
    }

    /**
     * Load the migrations for the test environment.
     *
     * @return void
     */
    protected function loadMigrations()
    {
        $this->loadMigrationsFrom([
            '--database' => 'sqlite',
            '--path' => realpath(__DIR__.'/Migrations'),
        ]);
    }

    protected function migrate()
    {
        $this->artisan('migrate')->run();
    }

    /**
     * Authenticate as an anonymous user.
     *
     * @return $this
     */
    protected function authenticate()
    {
        $this->actingAs($this->authenticatedAs = Mockery::mock(Authenticatable::class));

        $this->authenticatedAs->shouldReceive('getAuthIdentifier')->andReturn(1);
        $this->authenticatedAs->shouldReceive('getKey')->andReturn(1);

        return $this;
    }

    /**
     * Run the next job on the queue.
     *
     * @param  int  $times
     * @return void
     */
    protected function work($times = 1)
    {
        for ($i = 0; $i < $times; $i++) {
            $this->worker()->runNextJob(
                'redis', 'default', $this->workerOptions()
            );
        }
    }

    /**
     * Get the queue worker instance.
     *
     * @return \Illuminate\Queue\Worker
     */
    protected function worker()
    {
        return resolve('queue.worker');
    }

    /**
     * Get the options for the worker.
     *
     * @return \Illuminate\Queue\WorkerOptions
     */
    protected function workerOptions()
    {
        return tap(new WorkerOptions, function ($options) {
            $options->sleep = 0;
            $options->maxTries = 1;
        });
    }

    /**
     * Get the service providers for the package.
     *
     * @param  \Illuminate\Foundation\Application  $app
     * @return array
     */
    protected function getPackageProviders($app)
    {
        return [
            NovaCoreServiceProvider::class,
            NovaServiceProvider::class,
            TestServiceProvider::class,
        ];
    }

    /**
     * Define environment.
     *
     * @param  \Illuminate\Foundation\Application  $app
     * @return void
     */
    protected function getEnvironmentSetUp($app)
    {
        $app['config']->set('database.default', 'sqlite');

        $app['config']->set('database.connections.sqlite', [
            'driver'   => 'sqlite',
            'database' => ':memory:',
            'prefix'   => '',
        ]);
    }

    /**
     * Assert a top-level subset for an array.
     *
     * @param array $subset
     * @param array $array
     * @return void
     */
    public function assertSubset($subset, $array)
    {
        $values = collect($array)->only(array_keys($subset))->all();

        $this->assertEquals($subset, $values, 'The expected subset does not match the given array.');
    }

    /**
     * Configure ActionEvents to be on a separate database connection.
     *
     * @return void
     */
    protected function setupActionEventsOnSeparateConnection()
    {
        config(['nova.actions.resource' => CustomConnectionActionResource::class]);

        config([
            'database.connections.sqlite-custom' => [
                'driver' => 'sqlite',
                'database' => ':memory:',
                'prefix' => '',
            ],
        ]);

        Schema::connection('sqlite-custom')->create('action_events', function ($table) {
            $table->increments('id');
            $table->char('batch_id', 36);
            $table->unsignedInteger('user_id')->index();
            $table->string('name');
            $table->string('actionable_type');
            $table->unsignedInteger('actionable_id');
            $table->string('target_type');
            $table->unsignedInteger('target_id');
            $table->string('model_type');
            $table->unsignedInteger('model_id')->nullable();
            $table->text('fields');
            $table->string('status', 25)->default('running');
            $table->text('exception');
            $table->json('original')->nullable();
            $table->json('changes')->nullable();
            $table->timestamps();

            $table->index(['actionable_type', 'actionable_id']);
            $table->index(['batch_id', 'model_type', 'model_id']);
        });
    }
}
