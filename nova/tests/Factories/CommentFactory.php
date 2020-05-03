<?php

use Faker\Generator as Faker;

/*
|--------------------------------------------------------------------------
| Model Factories
|--------------------------------------------------------------------------
|
| This directory should contain each of the model factory definitions for
| your application. Factories provide a convenient way to generate new
| model instances for testing / seeding your application's database.
|
*/

$factory->define(Laravel\Nova\Tests\Fixtures\Comment::class, function (Faker $faker) {
    return [
        'commentable_id' => factory(Laravel\Nova\Tests\Fixtures\Post::class),
        'commentable_type' => Laravel\Nova\Tests\Fixtures\Post::class,
        'author_id' => factory(Laravel\Nova\Tests\Fixtures\User::class),
        'body' => $faker->word,
    ];
});
