<?php

namespace Laravel\Nova\Rules;

use Laravel\Nova\Nova;

class RelatableAttachment extends Relatable
{
    /**
     * Authorize that the user is allowed to relate this resource.
     *
     * @param  string  $resource
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return bool
     */
    protected function authorize($resource, $model)
    {
        $parentResource = Nova::resourceForModel(
            $parentModel = $this->request->findModelOrFail()
        );

        return (new $parentResource($parentModel))->authorizedToAttachAny(
            $this->request, $model
        ) || (new $parentResource($parentModel))->authorizedToAttach(
            $this->request, $model
        );
    }
}
