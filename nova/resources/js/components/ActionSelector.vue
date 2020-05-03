<template>
  <div>
    <div
      v-if="actions.length > 0 || availablePivotActions.length > 0"
      class="flex items-center mr-3"
    >
      <select
        data-testid="action-select"
        dusk="action-select"
        ref="selectBox"
        v-model="selectedActionKey"
        class="form-control form-select mr-2"
      >
        <option value="" disabled selected>{{ __('Select Action') }}</option>

        <optgroup
          v-if="actions.length > 0"
          :label="resourceInformation.singularLabel"
        >
          <option
            v-for="action in actions"
            :value="action.uriKey"
            :key="action.urikey"
            :selected="action.uriKey == selectedActionKey"
          >
            {{ action.name }}
          </option>
        </optgroup>

        <optgroup
          class="pivot-option-group"
          :label="pivotName"
          v-if="availablePivotActions.length > 0"
        >
          <option
            v-for="action in availablePivotActions"
            :value="action.uriKey"
            :key="action.urikey"
            :selected="action.uriKey == selectedActionKey"
          >
            {{ action.name }}
          </option>
        </optgroup>
      </select>

      <button
        data-testid="action-confirm"
        dusk="run-action-button"
        @click.prevent="determineActionStrategy"
        :disabled="!selectedAction"
        class="btn btn-default btn-primary flex items-center justify-center px-3"
        :class="{ 'btn-disabled': !selectedAction }"
        :title="__('Run Action')"
      >
        <icon type="play" class="text-white" style="margin-left: 7px;" />
      </button>
    </div>

    <!-- Action Confirmation Modal -->
    <portal to="modals" transition="fade-transition">
      <component
        v-if="confirmActionModalOpened"
        class="text-left"
        :is="selectedAction.component"
        :working="working"
        :selected-resources="selectedResources"
        :resource-name="resourceName"
        :action="selectedAction"
        :errors="errors"
        @confirm="executeAction"
        @close="closeConfirmationModal"
      />
    </portal>
  </div>
</template>

<script>
import _ from 'lodash'
import HandlesActions from '@/mixins/HandlesActions'
import { Errors, InteractsWithResourceInformation } from 'laravel-nova'

export default {
  mixins: [InteractsWithResourceInformation, HandlesActions],

  props: {
    selectedResources: {
      type: [Array, String],
      default: () => [],
    },
    pivotActions: {},
    pivotName: String,
  },

  watch: {
    /**
     * Watch the actions property for changes.
     */
    actions() {
      this.selectedActionKey = ''
      this.initializeActionFields()
    },

    /**
     * Watch the pivot actions property for changes.
     */
    pivotActions() {
      this.selectedActionKey = ''
      this.initializeActionFields()
    },
  },
}
</script>
