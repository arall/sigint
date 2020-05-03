<?php

namespace Laravel\Nova\Tests\Fixtures;

class UserPolicy
{
    /**
     * Determine if the given user can view resources.
     */
    public function viewAny($user)
    {
        return $_SERVER['nova.user.viewAnyable'] ?? true;
    }

    /**
     * Determine if the given user can view the given model.
     */
    public function view($user, $model)
    {
        return $_SERVER['nova.user.viewable'] ?? true;
    }

    /**
     * Determine if users can be created.
     */
    public function create($user)
    {
        return $_SERVER['nova.user.creatable'] ?? true;
    }

    /**
     * Determine if the given user can be updated.
     */
    public function update($user, $model)
    {
        return $_SERVER['nova.user.updatable'] ?? true;
    }

    /**
     * Determine if the given user can add posts to the given user.
     */
    public function addPost($user, $model)
    {
        $_SERVER['nova.user.addPostModel'] = $model;

        return $_SERVER['nova.user.addPost'] ?? true;
    }

    /**
     * Determine if the given user can attach any roles to the given user.
     */
    public function attachAnyRole($user, $userModel)
    {
        $_SERVER['nova.user.attachAnyRoleUser'] = $userModel;

        return $_SERVER['nova.user.attachAnyRole'] ?? true;
    }

    /**
     * Determine if the given user can attach roles to the given user.
     */
    public function attachRole($user, $userModel, $role)
    {
        $_SERVER['nova.user.attachRoleUser'] = $userModel;
        $_SERVER['nova.user.attachRoleRole'] = $role;

        return $_SERVER['nova.user.attachRole'] ?? true;
    }

    /**
     * Determine if the given user can detach roles from the given user.
     */
    public function detachRole($user, $userModel, $role)
    {
        $_SERVER['nova.user.detachRoleUser'] = $userModel;
        $_SERVER['nova.user.detachRoleRole'] = $role;

        return $_SERVER['nova.user.detachRole'] ?? true;
    }

    /**
     * Determine if the given user can be deleted.
     */
    public function delete($user, $model)
    {
        return $_SERVER['nova.user.deletable'] ?? true;
    }

    /**
     * Determine if the given user can be restored.
     */
    public function restore($user, $model)
    {
        return $_SERVER['nova.user.restorable'] ?? true;
    }

    /**
     * Determine if the given user can be force deleted.
     */
    public function forceDelete($user, $model)
    {
        return $_SERVER['nova.user.forceDeletable'] ?? true;
    }
}
