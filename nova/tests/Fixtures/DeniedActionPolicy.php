<?php

namespace Laravel\Nova\Tests\Fixtures;

class DeniedActionPolicy
{
    /**
     * Determine if the given user can view resources.
     */
    public function viewAny($user)
    {
        return false;
    }
}
