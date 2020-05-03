<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Fields\Text;
use Laravel\Nova\Panel;
use Laravel\Nova\Tests\IntegrationTest;

class PanelTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_panels_can_have_custom_help_text()
    {
        $panel = Panel::make('Personal Information', [
            Text::make('Name'),
        ])->help('Custom help text.');

        $this->assertSubset([
            'helpText' => 'Custom help text.',
        ], $panel->jsonSerialize());
    }
}
