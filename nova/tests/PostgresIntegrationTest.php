<?php

namespace Laravel\Nova\Tests;

abstract class PostgresIntegrationTest extends IntegrationTest
{
    protected function skipIfNotRunning()
    {
        if (! filter_var(getenv('RUN_POSTGRES_TESTS'), FILTER_VALIDATE_BOOLEAN)) {
            $this->markTestSkipped('Postgres tests not enabled.');

            return;
        }
    }

    /**
     * Load the migrations for the test environment.
     *
     * @return void
     */
    protected function loadMigrations()
    {
        $this->loadMigrationsFrom([
            '--database' => 'pgsql',
            '--path' => realpath(__DIR__.'/Migrations'),
            '--realpath' => true,
        ]);
    }

    /**
     * Define environment.
     *
     * @param  \Illuminate\Foundation\Application  $app
     * @return void
     */
    protected function getEnvironmentSetUp($app)
    {
        $app['config']->set('database.default', 'pgsql');

        $app['config']->set('database.connections.pgsql', [
            'driver' => 'pgsql',
            'host' => env('POSTGRES_HOST') ?? '127.0.0.1',
            'port' => env('POSTGRES_PORT') ?? 5432,
            'database' => env('POSTGRES_DB') ?? 'nova_test',
            'username' => env('POSTGRES_USER') ?? 'taylor',
            'password' => env('POSTGRES_PASSWORD') ?? '',
            'charset' => 'utf8',
            'prefix' => '',
            'schema' => 'public',
            'sslmode' => 'prefer',
        ]);
    }
}
