<?php

namespace Laravel\Nova\Tests\Fixtures;

class CommentPolicy
{
    /**
     * Determine if the given user can view resources.
     */
    public function viewAny($user)
    {
        return true;
    }

    /**
     * Determine if comments can be created.
     */
    public function create($user)
    {
        return $_SERVER['nova.comment.creatable'] ?? true;
    }

    /**
     * Determine if the given comment can be updated.
     */
    public function update($user, $model)
    {
        return $_SERVER['nova.comment.updatable'] ?? true;
    }

    /**
     * Determine if the given comment can be deleted.
     */
    public function delete($user, $model)
    {
        return $_SERVER['nova.comment.deletable'] ?? true;
    }
}
