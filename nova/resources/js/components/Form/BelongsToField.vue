<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <div class="flex items-center mb-3">
        <search-input
          v-if="isSearchable && !isLocked && !isReadonly"
          :data-testid="`${field.resourceName}-search-input`"
          @input="performSearch"
          @clear="clearSelection"
          @selected="selectResource"
          :error="hasError"
          :value="selectedResource"
          :data="availableResources"
          :clearable="field.nullable"
          trackBy="value"
          searchBy="display"
          class="w-full"
        >
          <div slot="default" v-if="selectedResource" class="flex items-center">
            <div v-if="selectedResource.avatar" class="mr-3">
              <img
                :src="selectedResource.avatar"
                class="w-8 h-8 rounded-full block"
              />
            </div>

            {{ selectedResource.display }}
          </div>

          <div
            slot="option"
            slot-scope="{ option, selected }"
            class="flex items-center"
          >
            <div v-if="option.avatar" class="mr-3">
              <img :src="option.avatar" class="w-8 h-8 rounded-full block" />
            </div>

            <div>
              <div
                class="text-sm font-semibold leading-5 text-90"
                :class="{ 'text-white': selected }"
              >
                {{ option.display }}
              </div>

              <div
                v-if="field.withSubtitles"
                class="mt-1 text-xs font-semibold leading-5 text-80"
                :class="{ 'text-white': selected }"
              >
                <span v-if="option.subtitle">{{ option.subtitle }}</span>
                <span v-else>{{ __('No additional information...') }}</span>
              </div>
            </div>
          </div>
        </search-input>

        <select-control
          v-if="!isSearchable || isLocked || isReadonly"
          class="form-control form-select w-full"
          :class="{ 'border-danger': hasError }"
          :data-testid="`${field.resourceName}-select`"
          :dusk="field.attribute"
          @change="selectResourceFromSelectControl"
          :disabled="isLocked || isReadonly"
          :options="availableResources"
          :value="selectedResourceId"
          :selected="selectedResourceId"
          label="display"
        >
          <option value="" selected :disabled="!field.nullable">{{
            placeholder
          }}</option>
        </select-control>

        <create-relation-button
          v-if="canShowNewRelationModal"
          @click="openRelationModal"
          class="ml-1"
        />
      </div>

      <portal to="modals" transition="fade-transition">
        <create-relation-modal
          v-if="relationModalOpen && canShowNewRelationModal"
          @set-resource="handleSetResource"
          @cancelled-create="closeRelationModal"
          :resource-name="field.resourceName"
          :resource-id="resourceId"
          :via-relationship="viaRelationship"
          :via-resource="viaResource"
          :via-resource-id="viaResourceId"
          width="800"
        />
      </portal>

      <!-- Trashed State -->
      <div v-if="shouldShowTrashed">
        <checkbox-with-label
          :dusk="`${field.resourceName}-with-trashed-checkbox`"
          :checked="withTrashed"
          @input="toggleWithTrashed"
        >
          {{ __('With Trashed') }}
        </checkbox-with-label>
      </div>
    </template>
  </default-field>
</template>

<script>
import _ from 'lodash'
import storage from '@/storage/BelongsToFieldStorage'
import {
  FormField,
  TogglesTrashed,
  PerformsSearches,
  HandlesValidationErrors,
} from 'laravel-nova'

export default {
  mixins: [
    TogglesTrashed,
    PerformsSearches,
    HandlesValidationErrors,
    FormField,
  ],

  props: {
    resourceId: {},
  },

  data: () => ({
    availableResources: [],
    initializingWithExistingResource: false,
    selectedResource: null,
    selectedResourceId: null,
    softDeletes: false,
    withTrashed: false,
    search: '',
    relationModalOpen: false,
  }),

  /**
   * Mount the component.
   */
  mounted() {
    this.initializeComponent()
  },

  methods: {
    initializeComponent() {
      this.withTrashed = false

      this.selectedResourceId = this.field.value

      // If a user is editing an existing resource with this relation
      // we'll have a belongsToId on the field, and we should prefill
      // that resource in this field
      if (this.editingExistingResource) {
        this.initializingWithExistingResource = true
        this.selectedResourceId = this.field.belongsToId
      }

      // If the user is creating this resource via a related resource's index
      // page we'll have a viaResource and viaResourceId in the params and
      // should prefill the resource in this field with that information
      if (this.creatingViaRelatedResource) {
        this.initializingWithExistingResource = true
        this.selectedResourceId = this.viaResourceId
      }

      if (this.shouldSelectInitialResource && !this.isSearchable) {
        // If we should select the initial resource but the field is not
        // searchable we should load all of the available resources into the
        // field first and select the initial option
        this.initializingWithExistingResource = false
        this.getAvailableResources().then(() => this.selectInitialResource())
      } else if (this.shouldSelectInitialResource && this.isSearchable) {
        // If we should select the initial resource and the field is
        // searchable, we won't load all the resources but we will select
        // the initial option
        // this.selectedResourceId = this.viaResourceId
        this.getAvailableResources().then(() => this.selectInitialResource())
      } else if (!this.shouldSelectInitialResource && !this.isSearchable) {
        // If we don't need to select an initial resource because the user
        // came to create a resource directly and there's no parent resource,
        // and the field is searchable we'll just load all of the resources
        this.getAvailableResources()
      }

      this.determineIfSoftDeletes()

      this.field.fill = this.fill
    },

    /**
     * Select a resource using the <select> control
     */
    selectResourceFromSelectControl(e) {
      this.selectedResourceId = e.target.value
      this.selectInitialResource()
    },

    /**
     * Fill the forms formData with details from this field
     */
    fill(formData) {
      formData.append(
        this.field.attribute,
        this.selectedResource ? this.selectedResource.value : ''
      )

      formData.append(this.field.attribute + '_trashed', this.withTrashed)
    },

    /**
     * Get the resources that may be related to this resource.
     */
    getAvailableResources() {
      return storage
        .fetchAvailableResources(
          this.resourceName,
          this.field.attribute,
          this.queryParams
        )
        .then(({ data: { resources, softDeletes, withTrashed } }) => {
          if (this.initializingWithExistingResource || !this.isSearchable) {
            this.withTrashed = withTrashed
          }

          // Turn off initializing the existing resource after the first time
          this.initializingWithExistingResource = false
          this.availableResources = resources
          this.softDeletes = softDeletes
        })
    },

    /**
     * Determine if the relatd resource is soft deleting.
     */
    determineIfSoftDeletes() {
      return storage
        .determineIfSoftDeletes(this.field.resourceName)
        .then(response => {
          this.softDeletes = response.data.softDeletes
        })
    },

    /**
     * Determine if the given value is numeric.
     */
    isNumeric(value) {
      return !isNaN(parseFloat(value)) && isFinite(value)
    },

    /**
     * Select the initial selected resource
     */
    selectInitialResource() {
      this.selectedResource = _.find(
        this.availableResources,
        r => r.value == this.selectedResourceId
      )
    },

    /**
     * Toggle the trashed state of the search
     */
    toggleWithTrashed() {
      this.withTrashed = !this.withTrashed

      // Reload the data if the component doesn't support searching
      if (!this.isSearchable) {
        this.getAvailableResources()
      }
    },

    openRelationModal() {
      this.relationModalOpen = true
    },

    closeRelationModal() {
      this.relationModalOpen = false
    },

    handleSetResource({ id }) {
      this.closeRelationModal()
      this.selectedResourceId = id
      this.getAvailableResources().then(() => this.selectInitialResource())
    },
  },

  computed: {
    /**
     * Determine if we are editing and existing resource
     */
    editingExistingResource() {
      return Boolean(this.field.belongsToId)
    },

    /**
     * Determine if we are creating a new resource via a parent relation
     */
    creatingViaRelatedResource() {
      return (
        this.viaResource == this.field.resourceName &&
        this.field.reverse &&
        this.viaResourceId
      )
    },

    /**
     * Determine if we should select an initial resource when mounting this field
     */
    shouldSelectInitialResource() {
      return Boolean(
        this.editingExistingResource || this.creatingViaRelatedResource
      )
    },

    /**
     * Determine if the related resources is searchable
     */
    isSearchable() {
      return this.field.searchable
    },

    /**
     * Get the query params for getting available resources
     */
    queryParams() {
      return {
        params: {
          current: this.selectedResourceId,
          first: this.initializingWithExistingResource,
          search: this.search,
          withTrashed: this.withTrashed,
          resourceId: this.resourceId,
          viaResource: this.viaResource,
          viaResourceId: this.viaResourceId,
          viaRelationship: this.viaRelationship,
        },
      }
    },

    isLocked() {
      return this.viaResource == this.field.resourceName && this.field.reverse
    },

    isReadonly() {
      return (
        this.field.readonly || _.get(this.field, 'extraAttributes.readonly')
      )
    },

    shouldShowTrashed() {
      return (
        this.softDeletes &&
        !this.isLocked &&
        !this.isReadonly &&
        this.field.displaysWithTrashed
      )
    },

    authorizedToCreate() {
      return _.find(Nova.config.resources, resource => {
        return resource.uriKey == this.field.resourceName
      }).authorizedToCreate
    },

    canShowNewRelationModal() {
      return (
        this.field.showCreateRelationButton &&
        !this.shownViaNewRelationModal &&
        !this.isLocked &&
        !this.isReadonly &&
        this.authorizedToCreate
      )
    },

    /**
     * Return the placeholder text for the field.
     */
    placeholder() {
      return this.field.placeholder || this.__('—')
    },
  },
}
</script>
