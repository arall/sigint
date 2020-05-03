<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Fields\ID;
use Laravel\Nova\Fields\VaporFile as NovaVaporFile;
use Laravel\Nova\Resource;

class VaporFileResource extends Resource
{
    /**
     * The model the resource corresponds to.
     *
     * @var string
     */
    public static $model = \Laravel\Nova\Tests\Fixtures\VaporFile::class;

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
            $this->avatarField(),
        ];
    }

    protected function avatarField()
    {
        return with(
            NovaVaporFile::make('Avatar', 'avatar')
                ->thumbnail(function ($value) {
                    return 'http://mycdn.com/image/'.$value;
                })
                ->storeOriginalName('original_name')
                ->prunable(),
            function ($field) {
                if ($_SERVER['nova.vaporFile.required'] ?? false) {
                    $field->rules('required');
                }

                return $field;
            }
        );
    }

    /**
     * Get the URI key for the resource.
     *
     * @return string
     */
    public static function uriKey()
    {
        return 'vapor-files';
    }
}
