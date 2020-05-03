<?php

namespace Laravel\Nova\Tests\Feature;

use Exception;
use Illuminate\Support\Carbon;
use Laravel\Nova\Fields\DateTime;
use PHPUnit\Framework\TestCase;

class DateTimeTest extends TestCase
{
    public function test_field_can_be_resolved()
    {
        Carbon::setTestNow(Carbon::parse('Oct 14 1984'));

        tap($this->dateTimeField(), function ($field) {
            $field->resolve((object) ['created_at' => Carbon::now()]);

            $this->assertEquals('1984-10-14 00:00:00', $field->value);

            Carbon::setTestNow();
        });
    }

    public function test_field_can_be_resolved_for_display()
    {
        Carbon::setTestNow(Carbon::parse('Oct 14 1984'));

        tap($this->dateTimeField(), function ($field) {
            $field->resolveForDisplay((object) ['created_at' => Carbon::now()]);

            $this->assertEquals('1984-10-14 00:00:00', $field->value);

            Carbon::setTestNow();
        });
    }

    public function test_field_can_be_resolved_with_null_value()
    {
        tap($this->dateTimeField(), function ($field) {
            tap((object) ['created_at' => null], function ($resource) use ($field) {
                $field->resolve($resource);
                $field->resolveForDisplay($resource);

                $this->assertNull($field->value);
            });
        });
    }

    public function test_field_throws_when_resolving_with_non_datetime_value()
    {
        $this->expectException(Exception::class);

        tap($this->dateTimeField(), function ($field) {
            tap((object) ['created_at' => 'wew'], function ($resource) use ($field) {
                $field->resolve($resource);
            });
        });
    }

    public function test_field_throws_when_resolving_for_display_with_non_datetime_value()
    {
        $this->expectException(Exception::class);

        tap($this->dateTimeField(), function ($field) {
            tap((object) ['created_at' => 'wew'], function ($resource) use ($field) {
                $field->resolveForDisplay($resource);
            });
        });
    }

    /**
     * Return a new DateTime field instance.
     *
     * @return \Laravel\Nova\Fields\DateTime
     */
    protected function dateTimeField()
    {
        return DateTime::make('Created At');
    }
}
