<?php

namespace Laravel\Nova\Tools;

use Laravel\Nova\Tool;

class Dashboard extends Tool
{
    /**
     * Build the view that renders the navigation links for the tool.
     *
     * @return \Illuminate\View\View
     */
    public function renderNavigation()
    {
        return view('nova::dashboard.navigation');
    }
}
