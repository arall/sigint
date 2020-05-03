<?php

namespace Laravel\Nova\Actions;

use DateTime;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\Relation;
use Illuminate\Support\Collection;
use Illuminate\Support\Str;
use Laravel\Nova\Http\Requests\ActionRequest;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Nova;

class ActionEvent extends Model
{
    /**
     * The attributes that aren't mass assignable.
     *
     * @var array
     */
    protected $guarded = [];

    /**
     * The attributes that should be cast to native types.
     *
     * @var array
     */
    protected $casts = [
        'original' => 'array',
        'changes' => 'array',
    ];

    /**
     * The storage format of the model's date columns.
     *
     * @var string
     */
    protected $dateFormat = 'Y-m-d H:i:s';

    /**
     * Get the user that initiated the action.
     */
    public function user()
    {
        return $this->belongsTo(config('auth.providers.users.model'), 'user_id');
    }

    /**
     * Get the target of the action for user interface linking.
     */
    public function target()
    {
        return $this->morphTo('target', 'target_type', 'target_id')->withTrashed();
    }

    /**
     * Create a new action event instance for a resource creation.
     *
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function forResourceCreate($user, $model)
    {
        return new static([
            'batch_id' => (string) Str::orderedUuid(),
            'user_id' => $user->getAuthIdentifier(),
            'name' => 'Create',
            'actionable_type' => $model->getMorphClass(),
            'actionable_id' => $model->getKey(),
            'target_type' => $model->getMorphClass(),
            'target_id' => $model->getKey(),
            'model_type' => $model->getMorphClass(),
            'model_id' => $model->getKey(),
            'fields' => '',
            'original' => null,
            'changes' => $model->attributesToArray(),
            'status' => 'finished',
            'exception' => '',
        ]);
    }

    /**
     * Create a new action event instance for a resource update.
     *
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function forResourceUpdate($user, $model)
    {
        return new static([
            'batch_id' => (string) Str::orderedUuid(),
            'user_id' => $user->getAuthIdentifier(),
            'name' => 'Update',
            'actionable_type' => $model->getMorphClass(),
            'actionable_id' => $model->getKey(),
            'target_type' => $model->getMorphClass(),
            'target_id' => $model->getKey(),
            'model_type' => $model->getMorphClass(),
            'model_id' => $model->getKey(),
            'fields' => '',
            'original' => array_intersect_key($model->getOriginal(), $model->getDirty()),
            'changes' => $model->getDirty(),
            'status' => 'finished',
            'exception' => '',
        ]);
    }

    /**
     * Create a new action event instance for an attached resource.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $parent
     * @param  \Illuminate\Database\Eloquent\Model  $pivot
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function forAttachedResource(NovaRequest $request, $parent, $pivot)
    {
        return new static([
            'batch_id' => (string) Str::orderedUuid(),
            'user_id' => $request->user()->getAuthIdentifier(),
            'name' => 'Attach',
            'actionable_type' => $parent->getMorphClass(),
            'actionable_id' => $parent->getKey(),
            'target_type' => Nova::modelInstanceForKey($request->relatedResource)->getMorphClass(),
            'target_id' => $parent->getKey(),
            'model_type' => $pivot->getMorphClass(),
            'model_id' => $pivot->getKey(),
            'fields' => '',
            'original' => null,
            'changes' => $pivot->attributesToArray(),
            'status' => 'finished',
            'exception' => '',
        ]);
    }

    /**
     * Create a new action event instance for an attached resource update.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  \Illuminate\Database\Eloquent\Model  $parent
     * @param  \Illuminate\Database\Eloquent\Model  $pivot
     * @return \Illuminate\Database\Eloquent\Model
     */
    public static function forAttachedResourceUpdate(NovaRequest $request, $parent, $pivot)
    {
        return new static([
            'batch_id' => (string) Str::orderedUuid(),
            'user_id' => $request->user()->getAuthIdentifier(),
            'name' => 'Update Attached',
            'actionable_type' => $parent->getMorphClass(),
            'actionable_id' => $parent->getKey(),
            'target_type' => Nova::modelInstanceForKey($request->relatedResource)->getMorphClass(),
            'target_id' => $request->relatedResourceId,
            'model_type' => $pivot->getMorphClass(),
            'model_id' => $pivot->getKey(),
            'fields' => '',
            'original' => array_intersect_key($pivot->getOriginal(), $pivot->getDirty()),
            'changes' => $pivot->getDirty(),
            'status' => 'finished',
            'exception' => '',
        ]);
    }

    /**
     * Create new action event instances for resource deletes.
     *
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Support\Collection  $models
     * @return \Illuminate\Support\Collection
     */
    public static function forResourceDelete($user, Collection $models)
    {
        return static::forSoftDeleteAction('Delete', $user, $models);
    }

    /**
     * Create new action event instances for resource restorations.
     *
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Support\Collection  $models
     * @return \Illuminate\Support\Collection
     */
    public static function forResourceRestore($user, Collection $models)
    {
        return static::forSoftDeleteAction('Restore', $user, $models);
    }

    /**
     * Create new action event instances for resource soft deletions.
     *
     * @param  string  $action
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Support\Collection  $models
     * @return \Illuminate\Support\Collection
     */
    public static function forSoftDeleteAction($action, $user, Collection $models)
    {
        $batchId = (string) Str::orderedUuid();

        return $models->map(function ($model) use ($action, $user, $batchId) {
            return new static([
                'batch_id' => $batchId,
                'user_id' => $user->getAuthIdentifier(),
                'name' => $action,
                'actionable_type' => $model->getMorphClass(),
                'actionable_id' => $model->getKey(),
                'target_type' => $model->getMorphClass(),
                'target_id' => $model->getKey(),
                'model_type' => $model->getMorphClass(),
                'model_id' => $model->getKey(),
                'fields' => '',
                'original' => null,
                'changes' => null,
                'status' => 'finished',
                'exception' => '',
                'created_at' => new DateTime,
                'updated_at' => new DateTime,
            ]);
        });
    }

    /**
     * Create new action event instances for resource detachments.
     *
     * @param  \Illuminate\Contracts\Auth\Authenticatable  $user
     * @param  \Illuminate\Database\Eloquent\Model  $parent
     * @param  \Illuminate\Support\Collection  $models
     * @param  string  $pivotClass
     * @return \Illuminate\Support\Collection
     */
    public static function forResourceDetach($user, $parent, Collection $models, $pivotClass)
    {
        $batchId = (string) Str::orderedUuid();

        return $models->map(function ($model) use ($user, $parent, $pivotClass, $batchId) {
            return new static([
                'batch_id' => $batchId,
                'user_id' => $user->getAuthIdentifier(),
                'name' => 'Detach',
                'actionable_type' => $parent->getMorphClass(),
                'actionable_id' => $parent->getKey(),
                'target_type' => $model->getMorphClass(),
                'target_id' => $model->getKey(),
                'model_type' => $pivotClass,
                'model_id' => null,
                'fields' => '',
                'original' => null,
                'changes' => null,
                'status' => 'finished',
                'exception' => '',
                'created_at' => new DateTime,
                'updated_at' => new DateTime,
            ]);
        });
    }

    /**
     * Create the action records for the given models.
     *
     * @param  \Laravel\Nova\Http\Requests\ActionRequest  $request
     * @param  \Laravel\Nova\Actions\Action  $action
     * @param  string  $batchId
     * @param  \Illuminate\Support\Collection  $models
     * @param  string  $status
     * @return void
     */
    public static function createForModels(ActionRequest $request, Action $action,
                                           $batchId, Collection $models, $status = 'running')
    {
        $models = $models->map(function ($model) use ($request, $action, $batchId, $status) {
            return array_merge(
                static::defaultAttributes($request, $action, $batchId, $status),
                [
                    'actionable_id' => $request->actionableKey($model),
                    'target_id' => $request->targetKey($model),
                    'model_id' => $model->getKey(),
                ]
            );
        });

        $models->chunk(50)->each(function ($models) {
            static::insert($models->all());
        });

        static::prune($models);
    }

    /**
     * Get the default attributes for creating a new action event.
     *
     * @param  \Laravel\Nova\Http\Requests\ActionRequest  $request
     * @param  \Laravel\Nova\Actions\Action  $action
     * @param  string  $batchId
     * @param  string  $status
     * @return array
     */
    public static function defaultAttributes(ActionRequest $request, Action $action,
                                             $batchId, $status = 'running')
    {
        if ($request->isPivotAction()) {
            $pivotClass = $request->pivotRelation()->getPivotClass();

            $modelType = collect(Relation::$morphMap)->filter(function ($model, $alias) use ($pivotClass) {
                return $model === $pivotClass;
            })->keys()->first() ?? $pivotClass;
        } else {
            $modelType = $request->actionableModel()->getMorphClass();
        }

        return [
            'batch_id' => $batchId,
            'user_id' => $request->user()->getAuthIdentifier(),
            'name' => $action->name(),
            'actionable_type' => $request->actionableModel()->getMorphClass(),
            'target_type' => $request->model()->getMorphClass(),
            'model_type' => $modelType,
            'fields' => serialize($request->resolveFieldsForStorage()),
            'original' => null,
            'changes' => null,
            'status' => $status,
            'exception' => '',
            'created_at' => new DateTime,
            'updated_at' => new DateTime,
        ];
    }

    /**
     * Prune the action events for the given types.
     *
     * @param  \Illuminate\Support\Collection  $models
     * @param  int  $limit
     */
    public static function prune($models, $limit = 25)
    {
        $models->each(function ($model) use ($limit) {
            static::where('actionable_id', $model['actionable_id'])
                ->where('actionable_type', $model['actionable_type'])
                ->whereNotIn('id', function ($query) use ($model, $limit) {
                    $query->select('id')->fromSub(
                        static::select('id')->orderBy('id', 'desc')
                                ->where('actionable_id', $model['actionable_id'])
                                ->where('actionable_type', $model['actionable_type'])
                                ->limit($limit)->toBase(),
                        'action_events_temp'
                    );
                })->delete();
        });
    }

    /**
     * Mark the given batch as running.
     *
     * @param  string  $batchId
     * @return int
     */
    public static function markBatchAsRunning($batchId)
    {
        return static::where('batch_id', $batchId)
                    ->whereNotIn('status', ['finished', 'failed'])->update([
                        'status' => 'running',
                    ]);
    }

    /**
     * Mark the given batch as finished.
     *
     * @param  string  $batchId
     * @return int
     */
    public static function markBatchAsFinished($batchId)
    {
        return static::where('batch_id', $batchId)
                    ->whereNotIn('status', ['finished', 'failed'])->update([
                        'status' => 'finished',
                    ]);
    }

    /**
     * Mark a given action event record as finished.
     *
     * @param  string  $batchId
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @return int
     */
    public static function markAsFinished($batchId, $model)
    {
        return static::updateStatus($batchId, $model, 'finished');
    }

    /**
     * Mark the given batch as failed.
     *
     * @param  string  $batchId
     * @param  \Throwable  $e
     * @return int
     */
    public static function markBatchAsFailed($batchId, $e = null)
    {
        return static::where('batch_id', $batchId)
                    ->whereNotIn('status', ['finished', 'failed'])->update([
                        'status' => 'failed',
                        'exception' => $e ? (string) $e : '',
                    ]);
    }

    /**
     * Mark a given action event record as failed.
     *
     * @param  string  $batchId
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @param  \Throwable|string  $e
     * @return int
     */
    public static function markAsFailed($batchId, $model, $e = null)
    {
        return static::updateStatus($batchId, $model, 'failed', $e);
    }

    /**
     * Update the status of a given action event.
     *
     * @param  string  $batchId
     * @param  \Illuminate\Database\Eloquent\Model  $model
     * @param  string  $status
     * @param  \Throwable|string  $e
     * @return int
     */
    public static function updateStatus($batchId, $model, $status, $e = null)
    {
        return static::where('batch_id', $batchId)
                        ->where('model_type', $model->getMorphClass())
                        ->where('model_id', $model->getKey())
                        ->update(['status' => $status, 'exception' => (string) $e]);
    }

    /**
     * Get the table associated with the model.
     *
     * @return string
     */
    public function getTable()
    {
        return 'action_events';
    }
}
