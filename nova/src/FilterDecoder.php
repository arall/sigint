<?php

namespace Laravel\Nova;

use Laravel\Nova\Query\ApplyFilter;

class FilterDecoder
{
    /**
     * The filter string to be decoded.
     *
     * @var string
     */
    protected $filterString;

    /**
     * The filters available via the request.
     *
     * @var \Illuminate\Support\Collection
     */
    protected $availableFilters;

    /**
     * Create a new FilterDecoder instance.
     *
     * @param  string  $filterString
     * @param  array|null  $availableFilters
     */
    public function __construct($filterString, $availableFilters = null)
    {
        $this->filterString = $filterString;
        $this->availableFilters = collect($availableFilters);
    }

    /**
     * Decode the given filters.
     *
     * @return array
     */
    public function filters()
    {
        if (empty($filters = $this->decodeFromBase64String())) {
            return collect();
        }

        return collect($filters)->map(function ($filter) {
            $matchingFilter = $this->availableFilters->first(function ($availableFilter) use ($filter) {
                return $filter['class'] === $availableFilter->key();
            });

            if ($matchingFilter) {
                return ['filter' => $matchingFilter, 'value' => $filter['value']];
            }
        })
            ->filter()
            ->reject(function ($filter) {
                if (is_array($filter['value'])) {
                    return count($filter['value']) < 1;
                } elseif (is_string($filter['value'])) {
                    return trim($filter['value']) === '';
                }

                return is_null($filter['value']);
            })->map(function ($filter) {
                return new ApplyFilter($filter['filter'], $filter['value']);
            })->values();
    }

    /**
     * Decode the filter string from base64 encoding.
     *
     * @return array
     */
    public function decodeFromBase64String()
    {
        if (empty($this->filterString)) {
            return [];
        }

        $filters = json_decode(base64_decode($this->filterString), true);

        return is_array($filters) ? $filters : [];
    }
}
