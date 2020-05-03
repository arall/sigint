<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Routing\Controller;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Nova;

class AttachedResourceUpdateController extends Controller
{
    use HandlesCustomRelationKeys;

    /**
     * Update an attached resource pivot record.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Illuminate\Http\Response
     */
    public function handle(NovaRequest $request)
    {
        $this->validate(
            $request, $model = $request->findModelOrFail(),
            $resource = $request->resource()
        );

        return DB::transaction(function () use ($request, $resource, $model) {
            $model->setRelation(
                $model->{$request->viaRelationship}()->getPivotAccessor(),
                $pivot = $this->findPivot($request, $model)
            );

            if ($this->modelHasBeenUpdatedSinceRetrieval($request, $pivot)) {
                return response('', 409);
            }

            [$pivot, $callbacks] = $resource::fillPivotForUpdate($request, $model, $pivot);

            Nova::actionEvent()->forAttachedResourceUpdate($request, $model, $pivot)->save();

            $pivot->save();

            collect($callbacks)->each->__invoke();
        });
    }

    /**
     * Validate the attachment request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @param  string  $resource
     * @return void
     */
    protected function validate(NovaRequest $request, $model, $resource)
    {
        $attribute = $resource::validationAttributeFor($request, $request->relatedResource);

        tap($this->updateRulesFor($request, $resource), function ($rules) use ($resource, $request, $attribute) {
            Validator::make($request->all(), $rules, [], $this->customRulesKeys($request, $attribute))->validate();

            $resource::validateForAttachmentUpdate($request);
        });
    }

    protected function updateRulesFor(NovaRequest $request, $resource)
    {
        $rules = $resource::updateRulesFor($request, $this->getRuleKey($request));

        if ($this->usingCustomRelationKey($request)) {
            $rules[$request->relatedResource] = $rules[$request->viaRelationship];
            unset($rules[$request->viaRelationship]);
        }

        return $rules;
    }

    /**
     * Find the pivot model for the operation.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return \Illuminate\Database\Eloquent\Model
     */
    protected function findPivot(NovaRequest $request, $model)
    {
        $pivot = $model->{$request->viaRelationship}()->getPivotAccessor();

        return $model->{$request->viaRelationship}()
                    ->withoutGlobalScopes()
                    ->lockForUpdate()
                    ->findOrFail($request->relatedResourceId)->{$pivot};
    }

    /**
     * Determine if the model has been updated since it was retrieved.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return void
     */
    protected function modelHasBeenUpdatedSinceRetrieval(NovaRequest $request, $model)
    {
        $column = $model->getUpdatedAtColumn();

        if (! $model->{$column}) {
            return false;
        }

        return $request->input('_retrieved_at') && $model->usesTimestamps() && $model->{$column}->gt(
            Carbon::createFromTimestamp($request->input('_retrieved_at'))
        );
    }
}
