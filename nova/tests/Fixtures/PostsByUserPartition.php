<?php

namespace Laravel\Nova\Tests\Fixtures;

use Illuminate\Http\Request;
use Laravel\Nova\Metrics\Partition;

class PostsByUserPartition extends Partition
{
    /**
     * Calculate the value of the metric.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return mixed
     */
    public function calculate(Request $request)
    {
        $query = (new Post)->addSelect('users.name')
                        ->join('users', 'posts.user_id', '=', 'users.id')
                        ->groupBy('users.name');

        return $this->count($request, $query, 'users.name');
    }

    /**
     * Get the URI key for the metric.
     *
     * @return string
     */
    public function uriKey()
    {
        return 'posts-by-user';
    }
}
