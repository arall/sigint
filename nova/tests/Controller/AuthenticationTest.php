<?php

namespace Laravel\Nova\Tests\Controller;

use Illuminate\Support\Facades\DB;
use Laravel\Nova\Nova;
use Laravel\Nova\Tests\Fixtures\User;
use Laravel\Nova\Tests\IntegrationTest;

class AuthenticationTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_access_is_denied_when_unauthenticated()
    {
        $response = $this->withExceptionHandling()
                        ->get('/nova-api/scripts/nova-tool');

        $response->assertStatus(302);

        $response = $this->withExceptionHandling()
                        ->getJson('/nova-api/scripts/nova-tool');

        $response->assertStatus(401);
    }

    // public function test_can_display_login_screen()
    // {
    //     $response = $this->withExceptionHandling()
    //                     ->get('/nova/login');

    //     $response->assertStatus(200);
    // }

    public function test_can_authenticate_users()
    {
        config(['auth.providers.users.model' => User::class]);

        $user = factory(User::class)->create([
            'email' => 'taylor@laravel.com',
            'password' => bcrypt('password'),
        ]);

        $response = $this->withExceptionHandling()
                        ->post('/nova/login', [
                            'email' => 'taylor@laravel.com',
                            'password' => 'password',
                        ]);

        $response->assertStatus(302);
        $this->assertAuthenticated();
        $this->assertEquals('http://localhost/nova', $response->headers->get('Location'));
    }

    // public function test_can_display_password_reset_link_request_screen()
    // {
    //     $response = $this->withExceptionHandling()
    //                     ->get('/nova/password/reset');

    //     $response->assertStatus(200);
    // }

    // public function test_can_request_password_reset_link_and_reset_password_using_token()
    // {
    //     DB::table('password_resets')->delete();

    //     config(['mail.driver' => 'array']);
    //     config(['auth.providers.users.model' => User::class]);

    //     // Request Password Reset Link...
    //     $user = factory(User::class)->create([
    //         'email' => 'taylor@laravel.com',
    //         'password' => bcrypt('password'),
    //     ]);

    //     $response = $this->withExceptionHandling()
    //                     ->post('/nova/password/email', [
    //                         'email' => 'taylor@laravel.com',
    //                     ]);

    //     $this->assertNotNull(User::$passwordResetToken);
    //     $response->assertStatus(302);
    //     $response->assertSessionHas('status', 'We have e-mailed your password reset link!');

    //     // Reset Password...
    //     $response = $this->withExceptionHandling()
    //                     ->get('/nova/password/reset/'.User::$passwordResetToken);

    //     $response->assertStatus(200);

    //     $response = $this->withExceptionHandling()
    //                     ->post('/nova/password/reset', [
    //                         'token' => User::$passwordResetToken,
    //                         'email' => 'taylor@laravel.com',
    //                         'password' => 'taylor',
    //                         'password_confirmation' => 'taylor',
    //                     ]);

    //     $response->assertStatus(302);
    //     $this->assertEquals('http://localhost/nova', $response->headers->get('Location'));
    // }
}
