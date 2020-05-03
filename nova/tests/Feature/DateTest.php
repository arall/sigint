<?php

namespace Laravel\Nova\Tests\Feature;

use Exception;
use Illuminate\Support\Carbon;
use Laravel\Nova\Fields\Date;
use PHPUnit\Framework\TestCase;

class DateTest extends TestCase
{
    public function test_field_can_be_resolved()
    {
        Carbon::setTestNow(Carbon::parse('Oct 14 1984'));

        tap($this->dateField(), function ($field) {
            $field->resolve((object) ['dob' => Carbon::now()]);

            $this->assertEquals('1984-10-14', $field->value);

            Carbon::setTestNow();
        });
    }

    public function test_field_can_be_resolved_for_display()
    {
        Carbon::setTestNow(Carbon::parse('Oct 14 1984'));

        tap($this->dateField(), function ($field) {
            $field->resolveForDisplay((object) ['dob' => Carbon::now()]);

            $this->assertEquals('1984-10-14', $field->value);

            Carbon::setTestNow();
        });
    }

    public function test_field_can_be_resolved_with_null_value()
    {
        tap($this->dateField(), function ($field) {
            tap((object) ['dob' => null], function ($resource) use ($field) {
                $field->resolve($resource);
                $field->resolveForDisplay($resource);

                $this->assertNull($field->value);
            });
        });
    }

    public function test_field_throws_when_resolving_with_non_datetime_value()
    {
        $this->expectException(Exception::class);

        tap($this->dateField(), function ($field) {
            tap((object) ['dob' => 'wew'], function ($resource) use ($field) {
                $field->resolve($resource);
            });
        });
    }

    public function test_field_throws_when_resolving_for_display_with_non_datetime_value()
    {
        $this->expectException(Exception::class);

        tap($this->dateField(), function ($field) {
            tap((object) ['dob' => 'wew'], function ($resource) use ($field) {
                $field->resolveForDisplay($resource);
            });
        });
    }

    /**
     * Return a new DateTime field instance.
     *
     * @return \Laravel\Nova\Fields\Date
     */
    protected function dateField()
    {
        return Date::make('Date Of Birth', 'dob');
    }
}
