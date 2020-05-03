<?php

namespace Laravel\Nova\Tools;

use Illuminate\Http\Request;
use Laravel\Nova\Nova;
use Laravel\Nova\Tool;

class ResourceManager extends Tool
{
    /**
     * Perform any tasks that need to happen on tool registration.
     *
     * @return void
     */
    public function boot()
    {
        Nova::provideToScript([
            'resources' => function (Request $request) {
                return Nova::resourceInformation($request);
            },
        ]);
    }

    /**
     * Build the view that renders the navigation links for the tool.
     *
     * @return \Illuminate\View\View
     */
    public function renderNavigation()
    {
        $request = request();
        $groups = Nova::groups($request);
        $navigation = Nova::groupedResourcesForNavigation($request);

        return view('nova::resources.navigation', [
            'navigation' => $navigation,
            'groups' => $groups,
        ]);
    }
}
