<?php

namespace Laravel\Nova\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Routing\Controller;

class RouterController extends Controller
{
    /**
     * Display the Nova Vue router.
     *
     * @return \Illuminate\Http\Response
     */
    public function show(Request $request)
    {
        return view('nova::router', [
            'user' => $request->user(),
        ]);
    }
}
