<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Session extends Model
{
    /**
     * Indicates if the model should be timestamped.
     *
     * @var bool
     */
    public $timestamps = false;

    /**
     * The attributes that should be cast to native types.
     *
     * @var array
     */
    protected $casts = [
        'started_at' => 'datetime',
        'finished_at' => 'datetime',
    ];

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
