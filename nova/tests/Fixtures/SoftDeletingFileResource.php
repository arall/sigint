<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\File;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Resource;

class SoftDeletingFileResource extends Resource
{
    /**
     * The model the resource corresponds to.
     *
     * @var string
     */
    public static $model = \Laravel\Nova\Tests\Fixtures\SoftDeletingFile::class;

    /**
     * The columns that should be searched.
     *
     * @var array
     */
    public static $search = [
        'id',
    ];

    /**
     * Get the fields displayed by the resource.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return array
     */
    public function fields(Request $request)
    {
        return [
            ID::make('ID', 'id'),

            File::make('Avatar', 'avatar', null, function ($request, $model) {
                return $request->avatar->storeAs('avatars', 'avatar.png');
            })->rules('required')->delete(function ($request) {
                $_SERVER['__nova.fileDeleted'] = true;

                return $_SERVER['__nova.fileDelete'] ?? null;
            })->prunable(),
        ];
    }

    /**
     * Get the URI key for the resource.
     *
     * @return string
     */
    public static function uriKey()
    {
        return 'soft-deleting-files';
    }
}
