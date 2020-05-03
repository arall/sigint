<?php

namespace Laravel\Nova\Tests\Fixtures;

class RolePolicy
{
    /**
     * Determine if the given user can view resources.
     */
    public function viewAny($user)
    {
        return true;
    }

    /**
     * Determine if the given role can be updated.
     */
    public function update($user, $model)
    {
        return $_SERVER['nova.role.updatable'] ?? true;
    }

    /**
     * Determine if the given role can be deleted.
     */
    public function delete($user, $model)
    {
        return $_SERVER['nova.role.deletable'] ?? true;
    }
}
