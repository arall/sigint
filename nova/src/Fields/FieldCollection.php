<?php

namespace Laravel\Nova\Fields;

use Illuminate\Http\Request;
use Illuminate\Support\Collection;
use Laravel\Nova\Contracts\ListableField;
use Laravel\Nova\Contracts\Resolvable;
use Laravel\Nova\Http\Requests\NovaRequest;

class FieldCollection extends Collection
{
    /**
     * Find a given field by its attribute.
     *
     * @param  string  $attribute
     * @param  mixed  $default
     * @return \Laravel\Nova\Fields\Field|null
     */
    public function findFieldByAttribute($attribute, $default = null)
    {
        return $this->first(function ($field) use ($attribute) {
            return isset($field->attribute) &&
                $field->attribute == $attribute;
        }, $default);
    }

    /**
     * Filter elements should be displayed for the given request.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function authorized(Request $request)
    {
        return $this->filter(function ($field) use ($request) {
            return $field->authorize($request);
        })->values();
    }

    /**
     * Filter elements should be displayed for the given request.
     *
     * @param  mixed  $resource
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function resolve($resource)
    {
        return $this->each(function ($field) use ($resource) {
            if ($field instanceof Resolvable) {
                $field->resolve($resource);
            }
        });
    }

    /**
     * Resolve value of fields for display.
     *
     * @param  mixed  $resource
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function resolveForDisplay($resource)
    {
        return $this->each(function ($field) use ($resource) {
            if ($field instanceof Resolvable) {
                $field->resolveForDisplay($resource);
            }
        });
    }

    /**
     * Filter fields for showing on detail.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  mixed  $resource
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function filterForDetail(NovaRequest $request, $resource)
    {
        return $this->filter(function ($field) use ($resource, $request) {
            return $field->isShownOnDetail($request, $resource);
        })->values();
    }

    /**
     * Filter fields for showing on index.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @param  mixed  $resource
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function filterForIndex(NovaRequest $request, $resource)
    {
        return $this->filter(function ($field) use ($resource, $request) {
            return $field->isShownOnIndex($request, $resource);
        })->values();
    }

    /**
     * Reject if the field is readonly.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function withoutReadonly(NovaRequest $request)
    {
        return $this->reject(function ($field) use ($request) {
            return $field->isReadonly($request);
        });
    }

    /**
     * Reject fields which use their own index listings.
     *
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function withoutListableFields()
    {
        return $this->reject(function ($field) {
            return $field instanceof ListableField;
        });
    }

    /**
     * Filter the fields to only many-to-many relationships.
     *
     * @return \Laravel\Nova\Fields\FieldCollection
     */
    public function filterForManyToManyRelations()
    {
        return $this->filter(function ($field) {
            return $field instanceof BelongsToMany || $field instanceof MorphToMany;
        });
    }
}
