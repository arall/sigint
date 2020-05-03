<?php

namespace Laravel\Nova\Tests\Feature;

use Laravel\Nova\Actions\Action;
use Laravel\Nova\Tests\IntegrationTest;

class ActionTest extends IntegrationTest
{
    public function setUp(): void
    {
        parent::setUp();
    }

    public function test_action_messages_can_be_generated()
    {
        $this->assertEquals(['message' => 'test'], Action::message('test'));
    }

    public function test_action_downloads_can_be_generated()
    {
        $this->assertEquals(['download' => 'test', 'name' => 'name'], Action::download('test', 'name'));
    }

    public function test_actions_respect_old_only_on_index_value()
    {
        $action = (new class extends Action {
            public $onlyOnIndex = true;
        });

        $this->assertShownOnIndex($action);
        $this->assertHiddenFromDetail($action);
        $this->assertHiddenFromTableRow($action);
    }

    public function test_actions_respect_old_only_on_detail_value()
    {
        $action = (new class extends Action {
            public $onlyOnDetail = true;
        });

        $this->assertHiddenFromIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertHiddenFromTableRow($action);
    }

    public function test_actions_should_be_hidden_from_the_table_row_by_default_and_shown_everywhere_else()
    {
        $action = (new class extends Action {
        });

        $this->assertShownOnIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertHiddenFromTableRow($action);
    }

    public function test_actions_can_be_shown_on_index()
    {
        $action = new class extends Action {
        };
        $action->showOnIndex = false;
        $action->showOnIndex();

        $this->assertShownOnIndex($action);
    }

    public function test_actions_can_be_shown_only_on_index()
    {
        $action = (new class extends Action {
        })->onlyOnIndex();

        $this->assertShownOnIndex($action);
        $this->assertHiddenFromDetail($action);
        $this->assertHiddenFromTableRow($action);

        $action->onlyOnIndex(false);

        $this->assertHiddenFromIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertShownOnTableRow($action);
    }

    public function test_actions_can_be_hidden_from_index()
    {
        $action = (new class extends Action {
        })->exceptOnIndex();

        $this->assertHiddenFromIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertShownOnTableRow($action);
    }

    public function test_actions_can_be_shown_on_detail()
    {
        $action = new class extends Action {
        };
        $action->showOnDetail = false;
        $action->showOnDetail();

        $this->assertShownOnDetail($action);
    }

    public function test_actions_can_be_shown_only_on_detail()
    {
        $action = (new class extends Action {
        })->onlyOnDetail();

        $this->assertHiddenFromIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertHiddenFromTableRow($action);

        $action->onlyOnDetail(false);

        $this->assertShownOnIndex($action);
        $this->assertHiddenFromDetail($action);
        $this->assertShownOnTableRow($action);
    }

    public function test_actions_can_be_hidden_from_detail()
    {
        $action = (new class extends Action {
        })->exceptOnDetail();

        $this->assertShownOnIndex($action);
        $this->assertHiddenFromDetail($action);
        $this->assertShownOnTableRow($action);
    }

    public function test_actions_can_be_shown_on_table_row()
    {
        $action = new class extends Action {
        };
        $action->showOnTableRow = false;
        $action->showOnTableRow();

        $this->assertShownOnTableRow($action);
    }

    public function test_actions_can_be_shown_only_on_table_row()
    {
        $action = (new class extends Action {
        })->onlyOnTableRow();

        $action->onlyOnTableRow(false);

        $this->assertShownOnIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertHiddenFromTableRow($action);
    }

    public function test_actions_can_be_hidden_from_table_row()
    {
        $action = (new class extends Action {
        })->exceptOnTableRow();

        $this->assertShownOnIndex($action);
        $this->assertShownOnDetail($action);
        $this->assertHiddenFromTableRow($action);
    }

    public function test_actions_can_have_custom_confirmation_button_text()
    {
        $action = new class extends Action {
        };

        $this->assertSubset(['confirmButtonText' => 'Run Action'], $action->jsonSerialize());

        $action->confirmButtonText('Yes!');

        $this->assertSubset(['confirmButtonText' => 'Yes!'], $action->jsonSerialize());
    }

    public function test_actions_can_have_custom_cancel_button_text()
    {
        $action = new class extends Action {
        };

        $this->assertSubset(['cancelButtonText' => 'Cancel'], $action->jsonSerialize());

        $action->cancelButtonText('Nah!');

        $this->assertSubset(['cancelButtonText' => 'Nah!'], $action->jsonSerialize());
    }

    public function test_actions_with_no_fields_can_have_custom_confirmation_text()
    {
        $action = new class extends Action {
        };

        $this->assertSubset(['confirmText' => 'Are you sure you want to run this action?'], $action->jsonSerialize());

        $action->confirmText('Are you sure!');

        $this->assertSubset(['confirmText' => 'Are you sure!'], $action->jsonSerialize());
    }

    protected function assertShownOnIndex(Action $action)
    {
        $this->assertTrue($action->shownOnIndex());
    }

    protected function assertShownOnDetail(Action $action)
    {
        $this->assertTrue($action->shownOnDetail());
    }

    protected function assertHiddenFromTableRow(Action $action)
    {
        $this->assertFalse($action->shownOnTableRow());
    }

    protected function assertShownOnTableRow(Action $action)
    {
        return $this->assertTrue($action->shownOnTableRow());
    }

    protected function assertHiddenFromDetail(Action $action)
    {
        $this->assertFalse($action->shownOnDetail());
    }

    protected function assertHiddenFromIndex(Action $action)
    {
        $this->assertFalse($action->shownOnIndex());
    }
}
