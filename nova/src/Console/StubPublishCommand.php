<?php

namespace Laravel\Nova\Console;

use Illuminate\Console\Command;
use Illuminate\Filesystem\Filesystem;

class StubPublishCommand extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'nova:stubs {--force : Overwrite any existing files}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Publish all stubs that are available for customization';

    /**
     * Execute the console command.
     *
     * @return void
     */
    public function handle()
    {
        if (! is_dir($stubsPath = $this->laravel->basePath('stubs/nova'))) {
            (new Filesystem)->makeDirectory($stubsPath, 0755, true);
        }

        $files = [
            __DIR__.'/stubs/action.stub' => $stubsPath.'/action.stub',
            __DIR__.'/stubs/base-resource.stub' => $stubsPath.'/base-resource.stub',
            __DIR__.'/stubs/boolean-filter.stub' => $stubsPath.'/boolean-filter.stub',
            __DIR__.'/stubs/dashboard.stub' => $stubsPath.'/dashboard.stub',
            __DIR__.'/stubs/date-filter.stub' => $stubsPath.'/date-filter.stub',
            __DIR__.'/stubs/destructive-action.stub' => $stubsPath.'/destructive-action.stub',
            __DIR__.'/stubs/filter.stub' => $stubsPath.'/filter.stub',
            __DIR__.'/stubs/lens.stub' => $stubsPath.'/lens.stub',
            __DIR__.'/stubs/partition.stub' => $stubsPath.'/partition.stub',
            __DIR__.'/stubs/resource.stub' => $stubsPath.'/resource.stub',
            __DIR__.'/stubs/trend.stub' => $stubsPath.'/trend.stub',
            __DIR__.'/stubs/user-resource.stub' => $stubsPath.'/user-resource.stub',
            __DIR__.'/stubs/value.stub' => $stubsPath.'/value.stub',
        ];

        foreach ($files as $from => $to) {
            if (! file_exists($to) || $this->option('force')) {
                file_put_contents($to, file_get_contents($from));
            }
        }

        $this->info('Nova stubs published successfully.');
    }
}
