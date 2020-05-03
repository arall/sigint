<?php

namespace Laravel\Nova\Console;

use Illuminate\Console\Command;
use Illuminate\Filesystem\Filesystem;
use Illuminate\Support\Str;
use Laravel\Nova\Console\Concerns\AcceptsNameAndVendor;
use Symfony\Component\Process\Process;

class CardCommand extends Command
{
    use AcceptsNameAndVendor, RenamesStubs;

    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'nova:card {name}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Create a new card';

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
            __DIR__.'/card-stubs',
            $this->cardPath()
        );

        // Card.js replacements...
        $this->replace('{{ title }}', $this->cardTitle(), $this->cardPath().'/resources/js/components/Card.vue');
        $this->replace('{{ component }}', $this->cardName(), $this->cardPath().'/resources/js/card.js');

        // Card.php replacements...
        $this->replace('{{ namespace }}', $this->cardNamespace(), $this->cardPath().'/src/Card.stub');
        $this->replace('{{ class }}', $this->cardClass(), $this->cardPath().'/src/Card.stub');
        $this->replace('{{ component }}', $this->cardName(), $this->cardPath().'/src/Card.stub');

        (new Filesystem)->move(
            $this->cardPath().'/src/Card.stub',
            $this->cardPath().'/src/'.$this->cardClass().'.php'
        );

        // CardServiceProvider.php replacements...
        $this->replace('{{ namespace }}', $this->cardNamespace(), $this->cardPath().'/src/CardServiceProvider.stub');
        $this->replace('{{ component }}', $this->cardName(), $this->cardPath().'/src/CardServiceProvider.stub');
        $this->replace('{{ name }}', $this->cardName(), $this->cardPath().'/src/CardServiceProvider.stub');

        // Card composer.json replacements...
        $this->replace('{{ name }}', $this->argument('name'), $this->cardPath().'/composer.json');
        $this->replace('{{ escapedNamespace }}', $this->escapedCardNamespace(), $this->cardPath().'/composer.json');

        // Rename the stubs with the proper file extensions...
        $this->renameStubs();

        // Register the card...
        $this->addCardRepositoryToRootComposer();
        $this->addCardPackageToRootComposer();
        $this->addScriptsToNpmPackage();

        if ($this->confirm("Would you like to install the card's NPM dependencies?", true)) {
            $this->installNpmDependencies();

            $this->output->newLine();
        }

        if ($this->confirm("Would you like to compile the card's assets?", true)) {
            $this->compile();

            $this->output->newLine();
        }

        if ($this->confirm('Would you like to update your Composer packages?', true)) {
            $this->composerUpdate();
        }
    }

    /**
     * Get the array of stubs that need PHP file extensions.
     *
     * @return array
     */
    protected function stubsToRename()
    {
        return [
            $this->cardPath().'/src/CardServiceProvider.stub',
            $this->cardPath().'/routes/api.stub',
        ];
    }

    /**
     * Add a path repository for the card to the application's composer.json file.
     *
     * @return void
     */
    protected function addCardRepositoryToRootComposer()
    {
        $composer = json_decode(file_get_contents(base_path('composer.json')), true);

        $composer['repositories'][] = [
            'type' => 'path',
            'url' => './'.$this->relativeCardPath(),
        ];

        file_put_contents(
            base_path('composer.json'),
            json_encode($composer, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Add a package entry for the card to the application's composer.json file.
     *
     * @return void
     */
    protected function addCardPackageToRootComposer()
    {
        $composer = json_decode(file_get_contents(base_path('composer.json')), true);

        $composer['require'][$this->argument('name')] = '*';

        file_put_contents(
            base_path('composer.json'),
            json_encode($composer, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Add a path repository for the card to the application's composer.json file.
     *
     * @return void
     */
    protected function addScriptsToNpmPackage()
    {
        $package = json_decode(file_get_contents(base_path('package.json')), true);

        $package['scripts']['build-'.$this->cardName()] = 'cd '.$this->relativeCardPath().' && npm run dev';
        $package['scripts']['build-'.$this->cardName().'-prod'] = 'cd '.$this->relativeCardPath().' && npm run prod';

        file_put_contents(
            base_path('package.json'),
            json_encode($package, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)
        );
    }

    /**
     * Install the card's NPM dependencies.
     *
     * @return void
     */
    protected function installNpmDependencies()
    {
        $this->executeCommand('npm set progress=false && npm install', $this->cardPath());
    }

    /**
     * Compile the card's assets.
     *
     * @return void
     */
    protected function compile()
    {
        $this->executeCommand('npm run dev', $this->cardPath());
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
     * Get the path to the card.
     *
     * @return string
     */
    protected function cardPath()
    {
        return base_path('nova-components/'.$this->cardClass());
    }

    /**
     * Get the relative path to the card.
     *
     * @return string
     */
    protected function relativeCardPath()
    {
        return 'nova-components/'.$this->cardClass();
    }

    /**
     * Get the card's namespace.
     *
     * @return string
     */
    protected function cardNamespace()
    {
        return Str::studly($this->cardVendor()).'\\'.$this->cardClass();
    }

    /**
     * Get the card's escaped namespace.
     *
     * @return string
     */
    protected function escapedCardNamespace()
    {
        return str_replace('\\', '\\\\', $this->cardNamespace());
    }

    /**
     * Get the card's class name.
     *
     * @return string
     */
    protected function cardClass()
    {
        return Str::studly($this->cardName());
    }

    /**
     * Get the card's vendor.
     *
     * @return string
     */
    protected function cardVendor()
    {
        return explode('/', $this->argument('name'))[0];
    }

    /**
     * Get the "title" name of the card.
     *
     * @return string
     */
    protected function cardTitle()
    {
        return Str::title(str_replace('-', ' ', $this->cardName()));
    }

    /**
     * Get the card's base name.
     *
     * @return string
     */
    protected function cardName()
    {
        return explode('/', $this->argument('name'))[1];
    }
}
