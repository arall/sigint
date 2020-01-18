<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Device extends Model
{
    /**
     * The attributes that are mass assignable.
     *
     * @var array
     */
    protected $fillable = [
        'identifier',
    ];

    /**
     * Device Type relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo
     */
    public function type()
    {
        return $this->belongsTo('App\Models\DeviceType');
    }

    /**
     * Entity relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo
     */
    public function entity()
    {
        return $this->belongsTo('App\Models\Entity');
    }

    /**
     * Sessions relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\hasMany
     */
    public function sessions()
    {
        return $this->hasMany('App\Models\Session');
    }

    /**
     * Logs relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\hasMany
     */
    public function logs()
    {
        return $this->hasMany('App\Models\Log');
    }
}
