<?php

namespace Laravel\Nova\Contracts;

interface Deletable
{
    /**
     * Specify the callback that should be used to delete the field.
     *
     * @param  callable  $deleteCallback
     * @return $this
     */
    public function delete(callable $deleteCallback);

    /**
     * Specify if the field is able to be deleted.
     *
     * @param  bool  $deletable
     * @return $this
     */
    public function deletable($deletable = true);

    /**
     * Determine if the field should be pruned when the resource is deleted.
     *
     * @return bool
     */
    public function isPrunable();

    /**
     * Specify if the field should be pruned when the resource is deleted.
     *
     * @param  bool  $prunable
     * @return $this
     */
    public function prunable($prunable = true);
}
