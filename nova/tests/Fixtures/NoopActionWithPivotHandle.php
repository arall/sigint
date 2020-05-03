<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Support\Collection;
use Laravel\Nova\Actions\Action;
use Laravel\Nova\Fields\ActionFields;

class NoopActionWithPivotHandle extends Action
{
    use ProvidesActionFields;

    public static $applied = [];
    public static $appliedFields = [];

    /**
     * Perform the action on the given role assignment models.
     *
     * @param  \Laravel\Nova\Fields\ActionFields  $fields
     * @param  \Illuminate\Support\Collection  $models
     * @return string|void
     */
    public function handleForRoleAssignments(ActionFields $fields, Collection $models)
    {
        static::$applied[] = $models;
        static::$appliedFields[] = $fields;
    }
}
