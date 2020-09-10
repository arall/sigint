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
        'identifier', 'name',
    ];

    /**
     * {@inheritDoc}
     */
    public static function boot()
    {
        parent::boot();

        static::creating(function ($model) {
            $min = 12;
            do {
                $mac = substr($model->identifier, 0, $min);
                $vendor = Vendor::whereHas('macs', function ($query) use ($mac) {
                    $query->whereMac($mac);
                })->first();
                if ($vendor) {
                    break;
                }
                $min--;
            } while ($min >= 8);
            if ($vendor) {
                $model->vendor()->associate($vendor);
            }
        });
    }

    /**
     * Set the identifier.
     *
     * @param  string  $value
     * @return void
     */
    public function setIdentifierAttribute($value)
    {
        $this->attributes['identifier'] = strtoupper($value);
    }

    /**
     * Vendor relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo
     */
    public function vendor()
    {
        return $this->belongsTo('App\Models\Vendor');
    }

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
     * Identity relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\BelongsTo
     */
    public function identity()
    {
        return $this->belongsTo('App\Models\Identity');
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
     * SSIDs relation.
     *
     * @return \Illuminate\Database\Eloquent\Relations\BelongsToMany
     */
    public function ssids()
    {
        return $this->belongsToMany('App\Models\Ssid', 'probes')->withTimestamps();
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
