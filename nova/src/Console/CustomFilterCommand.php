<?php

namespace Laravel\Nova\Console;

use Illuminate\Console\Command;
use Illuminate\Filesystem\Filesystem;
use Illuminate\Support\Str;
use Laravel\Nova\Console\Concerns\AcceptsNameAndVendor;
use Symfony\Component\Process\Process;

class CustomFilterCommand extends Command
{
    use AcceptsNameAndVendor, RenamesStubs;

    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'nova:custom-filter {name}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Create a new custom filter';

    /**
     * Execute the console command.
     *
     * @return void
     */
    public function handle()
    {
        if (! $this->hasValidNameArgument()) {
            return;
        }

        (new Filesystem)->copyDirectory(
            __DIR__.'/filter-stubs',
            $this->filterPath()
        );

        // Filter.js replacements...
        $this->replace('{{ component }}', $this->filterName(), $this->filterPath().'/resources/js/filter.js');

        // Filter.php replacements...
        $this->replace('{{ namespace }}', $this->filterNamespace(), $this->filterPath().'/src/Filter.stub');
        $this->replace('{{ class }}', $this->filterClass(), $this->filterPath().'/src/Filter.stub');
        $this->replace('{{ component }}', $this->filterName(), $this->filterPath().'/src/Filter.stub');

        (new Filesystem)->move(
            $this->filterPath().'/src/Filter.stub',
            $this->filterPath().'/src/'.$this->filterClass().'.php'
        );

        // FilterServiceProvider.php replacements...
        $this->replace('{{ namespace }}', $this->filterNamespace(), $this->filterPath().'/src/FilterServiceProvider.stub');
        $this->replace('{{ component }}', $this->filterName(), $this->filterPath().'/src/FilterServiceProvider.stub');

        // Filter composer.json replacements...
        $this->replace('{{ name }}', $this->argument('name'), $this->filterPath().'/composer.json');
        $this->replace('{{ escapedNamespace }}', $this->escapedFilterNamespace(), $this->filterPath().'/composer.json');

        // Rename the stubs with the proper file extensions...
        $this->renameStubs();

        // Register the filter...
        $this->addFilterRepositoryToRootComposer();
        $this->addFilterPackageToRootComposer();
        $this->addScriptsToNpmPackage();

        if ($this->confirm("Would you like to install the filter's NPM dependencies?", true)) {
            $this->installNpmDependencies();

            $this->output->newLine();
        }

        if ($this->confirm("Would you like to compile the filter's assets?", true)) {
            $this->compile();

            $this->output->newLine();
        }

        if ($this->confirm('Would you like to update your Composer packages?', true)) {
            $this->composerUpdate();
        }
    }

    /**
     * Get the stub file for the generator.
     *
     * @return string
     */
    protected function getStub()
    {
        return __DIR__.'/stubs/filter.stub';
    }

    /**
     * Get the default namespace for the class.
     *
     * @param  string  $rootNamespace
     * @return string
     */
    protected function getDefaultNamespace($rootNamespace)
    {
        return $rootNamespace.'\Nova\Filters';
    }

    /**
     * Get the array of stubs that need PHP file extensions.
     *
     * @return array
     */
    protected function stubsToRename()
    {
        return [
            $this->filterPath().'/src/FilterServiceProvider.stub',
        ];
    }

    /**
     * Add a path repository for the filter to the application's composer.json file.
     *
     * @return void
     */
    protected function addFilterRepositoryToRootComposer()
    {
        $composer = json_decode(file_get_contents(base_path('composer.json')), true);

        $composer['repositories'][] = [
            'type' => 'path',
            'url' => './'.$this->relativeFilterPath(),
        ];

        file_put_contents(
            base_path('composer.json'),
            json_encode($composer, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Add a package entry for the filter to the application's composer.json file.
     *
     * @return void
     */
    protected function addFilterPackageToRootComposer()
    {
        $composer = json_decode(file_get_contents(base_path('composer.json')), true);

        $composer['require'][$this->argument('name')] = '*';

        file_put_contents(
            base_path('composer.json'),
            json_encode($composer, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Add a path repository for the filter to the application's composer.json file.
     *
     * @return void
     */
    protected function addScriptsToNpmPackage()
    {
        $package = json_decode(file_get_contents(base_path('package.json')), true);

        $package['scripts']['build-'.$this->filterName()] = 'cd '.$this->relativeFilterPath().' && npm run dev';
        $package['scripts']['build-'.$this->filterName().'-prod'] = 'cd '.$this->relativeFilterPath().' && npm run prod';

        file_put_contents(
            base_path('package.json'),
            json_encode($package, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Install the filter's NPM dependencies.
     *
     * @return void
     */
    protected function installNpmDependencies()
    {
        $this->executeCommand('npm set progress=false && npm install', $this->filterPath());
    }

    /**
     * Compile the filter's assets.
     *
     * @return void
     */
    protected function compile()
    {
        $this->executeCommand('npm run dev', $this->filterPath());
    }

    /**
     * Update the project's composer dependencies.
     *
     * @return void
     */
    protected function composerUpdate()
    {
        $this->executeCommand('composer update', getcwd());
    }

    /**
     * Run the given command as a process.
     *
     * @param  string  $command
     * @param  string  $path
     * @return void
     */
    protected function executeCommand($command, $path)
    {
        $process = (Process::fromShellCommandline($command, $path))->setTimeout(null);

        if ('\\' !== DIRECTORY_SEPARATOR && file_exists('/dev/tty') && is_readable('/dev/tty')) {
            $process->setTty(true);
        }

        $process->run(function ($type, $line) {
            $this->output->write($line);
        });
    }

    /**
     * Replace the given string in the given file.
     *
     * @param  string  $search
     * @param  string  $replace
     * @param  string  $path
     * @return void
     */
    protected function replace($search, $replace, $path)
    {
        file_put_contents($path, str_replace($search, $replace, file_get_contents($path)));
    }

    /**
     * Get the path to the filter.
     *
     * @return string
     */
    protected function filterPath()
    {
        return base_path('nova-components/'.$this->filterClass());
    }

    /**
     * Get the relative path to the filter.
     *
     * @return string
     */
    protected function relativeFilterPath()
    {
        return 'nova-components/'.$this->filterClass();
    }

    /**
     * Get the filter's namespace.
     *
     * @return string
     */
    protected function filterNamespace()
    {
        return Str::studly($this->filterVendor()).'\\'.$this->filterClass();
    }

    /**
     * Get the filter's escaped namespace.
     *
     * @return string
     */
    protected function escapedFilterNamespace()
    {
        return str_replace('\\', '\\\\', $this->filterNamespace());
    }

    /**
     * Get the filter's class name.
     *
     * @return string
     */
    protected function filterClass()
    {
        return Str::studly($this->filterName());
    }

    /**
     * Get the filter's vendor.
     *
     * @return string
     */
    protected function filterVendor()
    {
        return explode('/', $this->argument('name'))[0];
    }

    /**
     * Get the "title" name of the filter.
     *
     * @return string
     */
    protected function filterTitle()
    {
        return Str::title(str_replace('-', ' ', $this->filterName()));
    }

    /**
     * Get the filter's base name.
     *
     * @return string
     */
    protected function filterName()
    {
        return explode('/', $this->argument('name'))[1];
    }
}
