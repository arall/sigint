<?php

namespace Laravel\Nova\Tests\Fixtures;

class TagPolicy
{
    /**
     * Determine if the given user can view resources.
     */
    public function viewAny($user)
    {
        return true;
    }

    /**
     * Determine if the given tag can be updated.
     */
    public function update($user, $model)
    {
        return $_SERVER['nova.tag.updatable'] ?? true;
    }

    /**
     * Determine if the given tag can be deleted.
     */
    public function delete($user, $model)
    {
        return $_SERVER['nova.tag.deletable'] ?? true;
    }
}
