<?php

namespace Laravel\Nova\Fields;

use Laravel\Nova\Http\Requests\NovaRequest;

class Code extends Field
{
    /**
     * The field's component.
     *
     * @var string
     */
    public $component = 'code-field';

    /**
     * Indicates if the field is used to manipulate JSON.
     *
     * @var bool
     */
    public $json = false;

    /**
     * The JSON encoding options.
     *
     * @var int|null
     */
    public $jsonOptions;

    /**
     * Indicates if the element should be shown on the index view.
     *
     * @var bool
     */
    public $showOnIndex = false;

    /**
     * Indicates the visual height of the Code editor.
     *
     * @var string|int
     */
    public $height = 300;

    /**
     * Resolve the given attribute from the given resource.
     *
     * @param  mixed  $resource
     * @param  string  $attribute
     * @return mixed
     */
    protected function resolveAttribute($resource, $attribute)
    {
        $value = parent::resolveAttribute($resource, $attribute);

        if ($this->json) {
            return is_array($value) || is_object($value)
                    ? json_encode($value, $this->jsonOptions ?? JSON_PRETTY_PRINT)
                    : json_encode(json_decode($value), $this->jsonOptions ?? JSON_PRETTY_PRINT);
        }

        return $value;
    }

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
            $model->{$attribute} = $this->json
                        ? json_decode($request[$requestAttribute], true)
                        : $request[$requestAttribute];
        }
    }

    /**
     * Indicate that the code field is used to manipulate JSON.
     *
     * @param  int|null  $options
     * @return $this
     */
    public function json($options = null)
    {
        $this->json = true;

        $this->jsonOptions = $options ?? JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE;

        return $this->options(['mode' => 'application/json']);
    }

    /**
     * Define the language syntax highlighting mode for the field.
     *
     * @param  string  $language
     * @return $this
     */
    public function language($language)
    {
        return $this->options(['mode' => $language]);
    }

    /**
     * Set the Code editor to display all of its contents.
     *
     * @return $this
     */
    public function fullHeight()
    {
        $this->height = '100%';

        return $this;
    }

    /**
     * Set the visual height of the Code editor to automatic.
     *
     * @return $this
     */
    public function autoHeight()
    {
        $this->height = 'auto';

        return $this;
    }

    /**
     * Set the visual height of the Code editor.
     *
     * @param string|int $height
     * @return $this
     */
    public function height($height)
    {
        $this->height = $height;

        return $this;
    }

    /**
     * Set configuration options for the code editor instance.
     *
     * @param  array  $options
     * @return $this
     */
    public function options($options)
    {
        $currentOptions = $this->meta['options'] ?? [];

        return $this->withMeta([
            'options' => array_merge($currentOptions, $options),
        ]);
    }

    /**
     * Prepare the field for JSON serialization.
     *
     * @return array
     */
    public function jsonSerialize()
    {
        return array_merge(parent::jsonSerialize(), [
            'height' => $this->height,
        ]);
    }
}
