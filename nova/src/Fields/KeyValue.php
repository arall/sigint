<?php

namespace Laravel\Nova\Fields;

use Laravel\Nova\Http\Requests\NovaRequest;

class KeyValue extends Field
{
    /**
     * The field's component.
     *
     * @var string
     */
    public $component = 'key-value-field';

    /**
     * Indicates if the element should be shown on the index view.
     *
     * @var bool
     */
    public $showOnIndex = false;

    /**
     * The label that should be used for the key heading.
     *
     * @var string
     */
    public $keyLabel;

    /**
     * The label that should be used for the value heading.
     *
     * @var string
     */
    public $valueLabel;

    /**
     * The label that should be used for the "add row" button.
     *
     * @var string
     */
    public $actionText;

    /**
     * The callback used to determine if the keys are readonly.
     *
     * @var \Closure
     */
    public $readonlyKeysCallback;

    /**
     * Determine if new rows are able to be added.
     *
     * @var bool
     */
    public $canAddRow = true;

    /**
     * Determine if rows are able to be deleted.
     *
     * @var bool
     */
    public $canDeleteRow = true;

    /**
     * Hydrate the given attribute on the model based on the incoming request.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  string  $requestAttribute
     * @param  object  $model
     * @param  string  $attribute
     * @return void
     */
    protected function fillAttributeFromRequest(NovaRequest $request, $requestAttribute, $model, $attribute)
    {
        if ($request->exists($requestAttribute)) {
            $model->{$attribute} = json_decode($request[$requestAttribute], true);
        }
    }

    /**
     * The label that should be used for the key table heading.
     *
     * @param  string  $label
     * @return $this
     */
    public function keyLabel($label)
    {
        $this->keyLabel = $label;

        return $this;
    }

    /**
     * The label that should be used for the value table heading.
     *
     * @param  string  $label
     * @return $this
     */
    public function valueLabel($label)
    {
        $this->valueLabel = $label;

        return $this;
    }

    /**
     * The label that should be used for the add row button.
     *
     * @param  string  $label
     * @return $this
     */
    public function actionText($label)
    {
        $this->actionText = $label;

        return $this;
    }

    /**
     * Set the callback used to determine if the keys are readonly.
     *
     * @param  \Closure|bool  $callback
     * @return $this
     */
    public function disableEditingKeys($callback = true)
    {
        $this->readonlyKeysCallback = $callback;

        return $this;
    }

    /**
     * Determine if the keys are readonly.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return bool
     */
    public function readonlyKeys(NovaRequest $request)
    {
        return with($this->readonlyKeysCallback, function ($callback) use ($request) {
            return is_callable($callback) ? call_user_func($callback, $request) : ($callback === true);
        });
    }

    /**
     * Disable adding new rows.
     *
     * @return $this
     */
    public function disableAddingRows()
    {
        $this->canAddRow = false;

        return $this;
    }

    /**
     * Disable deleting rows.
     *
     * @return $this
     */
    public function disableDeletingRows()
    {
        $this->canDeleteRow = false;

        return $this;
    }

    /**
     * Prepare the field element for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'keyLabel' => $this->keyLabel ?? __('Key'),
            'valueLabel' => $this->valueLabel ?? __('Value'),
            'actionText' => $this->actionText ?? __('Add row'),
            'readonlyKeys' => $this->readonlyKeys(app(NovaRequest::class)),
            'canAddRow' => $this->canAddRow,
            'canDeleteRow' => $this->canDeleteRow,
        ]);
    }
}
