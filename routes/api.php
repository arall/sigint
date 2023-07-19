<?php

use Illuminate\Support\Facades\Route;
use App\Http\Middleware\AuthenticateWithToken;

/*
|--------------------------------------------------------------------------
| API Routes
|--------------------------------------------------------------------------
|
| Here is where you can register API routes for your application. These
| routes are loaded by the RouteServiceProvider and all of them will
| be assigned to the "api" middleware group. Make something great!
|
*/

Route::post('logs', 'API\LogsController@store')->middleware(AuthenticateWithToken::class);
