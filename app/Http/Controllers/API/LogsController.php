<?php

namespace App\Http\Controllers\API;

use App\Http\Controllers\Controller;
use Illuminate\Http\Request;
use App\Models\DeviceType;
use Carbon\Carbon;

class LogsController extends Controller
{
    /**
     * Store a log.
     *
     * @param  int  $id
     * @return Response
     */
    public function store(Request $request)
    {
        $request->validate([
            'type_id' => 'required|exists:device_types,id',
            'identifier' => 'required',
            'time' => 'required',
            'signal' => 'required',
        ]);

        $type = DeviceType::findOrFail($request->type_id);
        $device = $type->devices()->firstOrCreate(['identifier' => $request->identifier]);

        // BT device name
        if (isset($request->name)) {
            $device->name = $request->name;
            $device->save();
        }

        // WiFi probe SSID
        if(isset($request->ssid)){
            $device->probes()->firstOrCreate(['ssid' => $request->ssid]);
        }

        $log = $device->logs()->create([
            'timestamp' => Carbon::createFromTimestamp($request->time),
            'signal' => isset($request->signal) ? $request->signal : null,
        ]);

        return response()->json(['id' => $log->id], 201);
    }
}