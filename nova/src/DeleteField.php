<?php

namespace Laravel\Nova;

use Laravel\Nova\Contracts\Storable;
use Laravel\Nova\Http\Requests\NovaRequest;

class DeleteField
{
    /**
     * Delete the given field.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Laravel\Nova\Fields\Field|\Laravel\Nova\Contracts\Deletable  $field
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function forRequest(NovaRequest $request, $field, $model)
    {
        $arguments = [
            $request,
            $model,
        ];

        if ($field instanceof Storable) {
            array_push($arguments, $field->getStorageDisk(), $field->getStoragePath());
        }

        $result = call_user_func_array($field->deleteCallback, $arguments);

        if ($result === true) {
            return $model;
        }

        if (! is_array($result)) {
            $model->{$field->attribute} = $result;
        } else {
            foreach ($result as $key => $value) {
                $model->{$key} = $value;
            }
        }

        return $model;
    }
}
