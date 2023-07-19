<?php

namespace App\Nova\Lenses\Devices;

use Laravel\Nova\Fields\Text;
use Laravel\Nova\Http\Requests\LensRequest;
use Laravel\Nova\Http\Requests\NovaRequest;
use Laravel\Nova\Lenses\Lens;
use Illuminate\Support\Facades\DB;

class Top extends Lens
{
    /**
     * Get the query builder / paginator for the lens.
     *
     * @param  \Laravel\Nova\Http\Requests\LensRequest  $request
     * @param  \Illuminate\Database\Eloquent\Builder  $query
     * @return mixed
     */
    public static function query(LensRequest $request, $query)
    {
        return $request->withOrdering($request->withFilters(
            $query->select([
                DB::raw('device_types.name as type'),
                'devices.id',
                DB::raw('vendors.name as vendor'),
                DB::raw('identities.name as identity'),
                'identifier',
                'devices.name'
            ])
                ->leftJoin('device_types', 'device_types.id', '=', 'devices.type_id')
                ->leftJoin('vendors', 'vendors.id', '=', 'devices.vendor_id')
                ->leftJoin('identities', 'identities.id', '=', 'devices.identity_id')
                ->leftJoin('logs', 'logs.device_id', '=', 'devices.id')
                ->leftJoin('probes', 'probes.device_id', '=', 'devices.id')
                ->groupBy([
                    'devices.id',
                ])
                ->withCount('logs')
                ->withCount('probes')
                ->orderBy('logs_count', 'desc')
        ));
    }

    /**
     * Get the fields available to the lens.
     *
     * @param  \Laravel\Nova\Http\Requests\NovaRequest  $request
     * @return array
     */
    public function fields(NovaRequest $request)
    {
        return [
            Text::make('ID', 'id'),
            Text::make('Type'),
            Text::make('Vendor'),
            Text::make('Identity'),
            Text::make('Identifier'),
            Text::make('Name'),
            Text::make('# Logs', 'logs_count'),
            Text::make('# Probes', ' probes_count'),
        ];
    }

    /**
     * Get the URI key for the lens.
     *
     * @return string
     */
    public function uriKey()
    {
        return 'devices-top';
    }
}
