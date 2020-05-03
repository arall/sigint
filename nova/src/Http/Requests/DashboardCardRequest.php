<?php

namespace Laravel\Nova\Http\Requests;

use Laravel\Nova\Nova;

class DashboardCardRequest extends NovaRequest
{
    /**
     * Get all of the possible cards for the request.
     *
     * @param  string  $dashboard
     *
     * @return \Illuminate\Support\Collection
     */
    public function availableCards($dashboard)
    {
        if ($dashboard === 'main') {
            return collect(Nova::$defaultDashboardCards)
                ->unique()
                ->filter
                ->authorize($this)
                ->values();
        }

        return Nova::availableDashboardCardsForDashboard($dashboard, $this);
    }
}
