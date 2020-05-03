<?php

namespace Laravel\Nova\Rules;

use Illuminate\Contracts\Validation\Rule;
use Laravel\Nova\Fields\HasOne;
use Laravel\Nova\Fields\MorphOne;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Nova;

class Relatable implements Rule
{
    /**
     * The request instance.
     *
     * @var \Laravel\Nova\Http\Requests\NovaRequest
     */
    public $request;

    /**
     * The query builder instance.
     *
     * @var \Illuminate\Database\Eloquent\Builder
     */
    public $query;

    /**
     * Create a new rule instance.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return void
     */
    public function __construct(NovaRequest $request, $query)
    {
        $this->query = $query;
        $this->request = $request;
    }

    /**
     * Determine if the validation rule passes.
     *
     * @param  string  $attribute
     * @param  mixed  $value
     * @return bool
     */
    public function passes($attribute, $value)
    {
        $model = $this->query->select('*')->whereKey($value)->first();

        if (! $model) {
            return false;
        }

        if ($this->relationshipIsFull($model, $attribute, $value)) {
            return false;
        }

        if ($resource = Nova::resourceForModel($model)) {
            return $this->authorize($resource, $model);
        }

        return true;
    }

    /**
     * Determine if the relationship is "full".
     *
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @param  string  $attribute
     * @param  mixed  $value
     * @return bool
     */
    protected function relationshipIsFull($model, $attribute, $value)
    {
        $inverseRelation = $this->request->newResource()
                    ->resolveInverseFieldsForAttribute($this->request, $attribute)->first(function ($field) {
                        return $field instanceof HasOne || $field instanceof MorphOne;
                    });

        if ($inverseRelation && $this->request->resourceId) {
            $modelBeingUpdated = $this->request->findModelOrFail();

            if (is_null($modelBeingUpdated->{$attribute})) {
                return false;
            }

            if ($modelBeingUpdated->{$attribute}->getKey() == $value) {
                return false;
            }
        }

        return $inverseRelation &&
               $model->{$inverseRelation->attribute}()->count() > 0;
    }

    /**
     * Authorize that the user is allowed to relate this resource.
     *
     * @param  string  $resource
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return bool
     */
    protected function authorize($resource, $model)
    {
        return (new $resource($model))->authorizedToAdd(
            $this->request, $this->request->model()
        );
    }

    /**
     * Get the validation error message.
     *
     * @return string
     */
    public function message()
    {
        return trans('nova::validation.relatable');
    }
}
