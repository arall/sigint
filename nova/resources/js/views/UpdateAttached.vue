<template>
  <loading-view :loading="loading">
    <custom-update-attached-header
      class="mb-3"
      :resource-name="resourceName"
      :resource-id="resourceId"
    />

    <heading class="mb-3">{{
      __('Update :resource', { resource: relatedResourceLabel })
    }}</heading>

    <form
      v-if="field"
      @submit.prevent="updateAttachedResource"
      autocomplete="off"
    >
      <card class="overflow-hidden mb-8">
        <!-- Related Resource -->
        <default-field :field="field" :errors="validationErrors">
          <template slot="field">
            <select-control
              class="form-control form-select mb-3 w-full"
              dusk="attachable-select"
              :class="{
                'border-danger': validationErrors.has(field.attribute),
              }"
              :data-testid="`${field.resourceName}-select`"
              @change="selectResourceFromSelectControl"
              disabled
              :options="availableResources"
              :label="'display'"
              :selected="selectedResourceId"
            >
              <option value="" disabled selected>{{
                __('Choose :field', { field: field.name })
              }}</option>
            </select-control>
          </template>
        </default-field>

        <!-- Pivot Fields -->
        <div v-for="field in fields">
          <component
            :is="'form-' + field.component"
            :resource-name="resourceName"
            :resource-id="resourceId"
            :field="field"
            :errors="validationErrors"
            :related-resource-name="relatedResourceName"
            :related-resource-id="relatedResourceId"
            :via-resource="viaResource"
            :via-resource-id="viaResourceId"
            :via-relationship="viaRelationship"
          />
        </div>
      </card>
      <!-- Attach Button -->
      <div class="flex items-center">
        <cancel-button @click="$router.back()" />

        <progress-button
          class="mr-3"
          dusk="update-and-continue-editing-button"
          @click.native="updateAndContinueEditing"
          :disabled="isWorking"
          :processing="submittedViaUpdateAndContinueEditing"
        >
          {{ __('Update & Continue Editing') }}
        </progress-button>

        <progress-button
          dusk="update-button"
          type="submit"
          :disabled="isWorking"
          :processing="submittedViaUpdateAttachedResource"
        >
          {{
            __('Update :resource', {
              resource: relatedResourceLabel,
            })
          }}
        </progress-button>
      </div>
    </form>
  </loading-view>
</template>

<script>
import _ from 'lodash'
import { PerformsSearches, TogglesTrashed, Errors } from 'laravel-nova'

export default {
  mixins: [PerformsSearches, TogglesTrashed],

  props: {
    resourceName: {
      type: String,
      required: true,
    },
    resourceId: {
      required: true,
    },
    relatedResourceName: {
      type: String,
      required: true,
    },
    relatedResourceId: {
      required: true,
    },
    viaResource: {
      default: '',
    },
    viaResourceId: {
      default: '',
    },
    viaRelationship: {
      default: '',
    },
    polymorphic: {
      default: false,
    },
  },

  data: () => ({
    loading: true,
    submittedViaUpdateAndContinueEditing: false,
    submittedViaUpdateAttachedResource: false,
    field: null,
    softDeletes: false,
    fields: [],
    validationErrors: new Errors(),
    selectedResource: null,
    selectedResourceId: null,
    lastRetrievedAt: null,
  }),

  created() {
    if (Nova.missingResource(this.resourceName))
      return this.$router.push({ name: '404' })
  },

  /**
   * Mount the component.
   */
  mounted() {
    this.initializeComponent()
  },

  methods: {
    /**
     * Initialize the component's data.
     */
    async initializeComponent() {
      this.softDeletes = false
      this.disableWithTrashed()
      this.clearSelection()
      this.getField()

      await this.getPivotFields()
      await this.getAvailableResources()

      this.selectedResourceId = this.relatedResourceId

      this.selectInitialResource()

      this.updateLastRetrievedAtTimestamp()
    },

    /**
     * Get the many-to-many relationship field.
     */
    getField() {
      this.field = null

      Nova.request()
        .get(
          '/nova-api/' + this.resourceName + '/field/' + this.viaRelationship
        )
        .then(({ data }) => {
          this.field = data

          if (this.field.searchable) {
            this.determineIfSoftDeletes()
          }

          this.loading = false
        })
    },

    /**
     * Get all of the available pivot fields for the relationship.
     */
    async getPivotFields() {
      this.fields = []

      const { data } = await Nova.request()
        .get(
          `/nova-api/${this.resourceName}/${this.resourceId}/update-pivot-fields/${this.relatedResourceName}/${this.relatedResourceId}`,
          {
            params: {
              editing: true,
              editMode: 'update-attached',
              viaRelationship: this.viaRelationship,
            },
          }
        )
        .catch(error => {
          if (error.response.status == 404) {
            this.$router.push({ name: '404' })
            return
          }
        })

      this.fields = data

      _.each(this.fields, field => {
        field.fill = () => ''
      })
    },

    /**
     * Get all of the available resources for the current search / trashed state.
     */
    async getAvailableResources(search = '') {
      try {
        const response = await Nova.request().get(
          `/nova-api/${this.resourceName}/${this.resourceId}/attachable/${this.relatedResourceName}`,
          {
            params: {
              search,
              current: this.relatedResourceId,
              first: true,
              withTrashed: this.withTrashed,
            },
          }
        )

        this.availableResources = response.data.resources
        this.withTrashed = response.data.withTrashed
        this.softDeletes = response.data.softDeletes
      } catch (error) {
        console.log(error)
      }
    },

    /**
     * Determine if the related resource is soft deleting.
     */
    determineIfSoftDeletes() {
      Nova.request()
        .get('/nova-api/' + this.relatedResourceName + '/soft-deletes')
        .then(response => {
          this.softDeletes = response.data.softDeletes
        })
    },

    /**
     * Update the attached resource.
     */
    async updateAttachedResource() {
      this.submittedViaUpdateAttachedResource = true

      try {
        await this.updateRequest()

        this.submittedViaUpdateAttachedResource = false

        Nova.success(this.__('The resource was updated!'))

        this.$router.push({
          name: 'detail',
          params: {
            resourceName: this.resourceName,
            resourceId: this.resourceId,
          },
        })
      } catch (error) {
        this.submittedViaUpdateAttachedResource = false

        if (error.response.status == 422) {
          this.validationErrors = new Errors(error.response.data.errors)
          Nova.error(this.__('There was a problem submitting the form.'))
        }

        if (error.response.status == 409) {
          Nova.error(
            this.__(
              'Another user has updated this resource since this page was loaded. Please refresh the page and try again.'
            )
          )
        }
      }
    },

    /**
     * Update the resource and reset the form
     */
    async updateAndContinueEditing() {
      this.submittedViaUpdateAndContinueEditing = true

      try {
        await this.updateRequest()

        this.submittedViaUpdateAndContinueEditing = false

        Nova.success(this.__('The resource was updated!'))

        // Reset the form by refetching the fields
        this.initializeComponent()
      } catch (error) {
        this.submittedViaUpdateAndContinueEditing = false

        if (error.response.status == 422) {
          this.validationErrors = new Errors(error.response.data.errors)
          Nova.error(this.__('There was a problem submitting the form.'))
        }

        if (error.response.status == 409) {
          Nova.error(
            this.__(
              'Another user has updated this resource since this page was loaded. Please refresh the page and try again.'
            )
          )
        }
      }
    },

    /**
     * Send an update request for this resource
     */
    updateRequest() {
      return Nova.request().post(
        `/nova-api/${this.resourceName}/${this.resourceId}/update-attached/${this.relatedResourceName}/${this.relatedResourceId}`,
        this.updateAttachmentFormData,
        {
          params: {
            editing: true,
            editMode: 'update-attached',
          },
        }
      )
    },

    /**
     * Select a resource using the <select> control
     */
    selectResourceFromSelectControl(e) {
      this.selectedResourceId = e.target.value
      console.log(e.target.value, this.selectedResourceId)
      this.selectInitialResource()
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
     * Update the last retrieved at timestamp to the current UNIX timestamp.
     */
    updateLastRetrievedAtTimestamp() {
      this.lastRetrievedAt = Math.floor(new Date().getTime() / 1000)
    },
  },

  computed: {
    /**
     * Get the attachment endpoint for the relationship type.
     */
    attachmentEndpoint() {
      return this.polymorphic
        ? '/nova-api/' +
            this.resourceName +
            '/' +
            this.resourceId +
            '/attach-morphed/' +
            this.relatedResourceName
        : '/nova-api/' +
            this.resourceName +
            '/' +
            this.resourceId +
            '/attach/' +
            this.relatedResourceName
    },

    /*
     * Get the form data for the resource attachment update.
     */
    updateAttachmentFormData() {
      return _.tap(new FormData(), formData => {
        _.each(this.fields, field => {
          field.fill(formData)
        })

        formData.append('viaRelationship', this.viaRelationship)

        if (!this.selectedResource) {
          formData.append(this.relatedResourceName, '')
        } else {
          formData.append(this.relatedResourceName, this.selectedResource.value)
        }

        formData.append(this.relatedResourceName + '_trashed', this.withTrashed)
        formData.append('_retrieved_at', this.lastRetrievedAt)
      })
    },

    /**
     * Get the label for the related resource.
     */
    relatedResourceLabel() {
      if (this.field) {
        return this.field.singularLabel
      }
    },

    /**
     * Determine if the related resources is searchable
     */
    isSearchable() {
      return this.field.searchable
    },

    /**
     * Determine if the form is being processed
     */
    isWorking() {
      return (
        this.submittedViaUpdateAttachedResource ||
        this.submittedViaUpdateAndContinueEditing
      )
    },
  },
}
</script>
