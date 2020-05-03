<?php

namespace Laravel\Nova\Tests\Fixtures;

use Laravel\Nova\Actions\Action;
use Laravel\Nova\Actions\ActionModelCollection;
use Laravel\Nova\Fields\ActionFields;

class HandleResultAction extends Action
{
    public static $chunkCount = 50;

    public function handle(ActionFields $fields, ActionModelCollection $models)
    {
        return $models->count();
    }

    public function handleResult(ActionFields $fields, $results)
    {
        $count = array_reduce($results, function ($a, $b) {
            return $a + $b;
        }, 0);

        return Action::message("Processed {$count} records");
    }
}
