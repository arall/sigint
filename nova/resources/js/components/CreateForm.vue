<template>
  <loading-view :loading="loading">
    <custom-create-header class="mb-3" :resource-name="resourceName" />

    <form
      v-if="panels"
      @submit="submitViaCreateResource"
      autocomplete="off"
      ref="form"
    >
      <form-panel
        class="mb-8"
        v-for="panel in panelsWithFields"
        @file-upload-started="handleFileUploadStarted"
        @file-upload-finished="handleFileUploadFinished"
        :shown-via-new-relation-modal="shownViaNewRelationModal"
        :panel="panel"
        :name="panel.name"
        :key="panel.name"
        :resource-name="resourceName"
        :fields="panel.fields"
        mode="form"
        :validation-errors="validationErrors"
        :via-resource="viaResource"
        :via-resource-id="viaResourceId"
        :via-relationship="viaRelationship"
      />

      <!-- Create Button -->
      <div class="flex items-center">
        <cancel-button @click="$emit('cancelled-create')" />

        <progress-button
          v-if="shouldShowAddAnotherButton"
          dusk="create-and-add-another-button"
          class="mr-3"
          @click.native="submitViaCreateResourceAndAddAnother"
          :disabled="isWorking"
          :processing="wasSubmittedViaCreateResourceAndAddAnother"
        >
          {{ __('Create & Add Another') }}
        </progress-button>

        <progress-button
          dusk="create-button"
          type="submit"
          :disabled="isWorking"
          :processing="wasSubmittedViaCreateResource"
        >
          {{ __('Create :resource', { resource: singularName }) }}
        </progress-button>
      </div>
    </form>
  </loading-view>
</template>

<script>
import {
  mapProps,
  Errors,
  Minimum,
  InteractsWithResourceInformation,
} from 'laravel-nova'
import HandlesUploads from '@/mixins/HandlesUploads'

export default {
  mixins: [InteractsWithResourceInformation, HandlesUploads],

  props: {
    mode: {
      type: String,
      default: 'form',
      validator: val => ['modal', 'form'].includes(val),
    },

    ...mapProps([
      'resourceName',
      'viaResource',
      'viaResourceId',
      'viaRelationship',
    ]),
  },

  data: () => ({
    relationResponse: null,
    loading: true,
    submittedViaCreateResourceAndAddAnother: false,
    submittedViaCreateResource: false,
    fields: [],
    panels: [],
    validationErrors: new Errors(),
  }),

  async created() {
    if (Nova.missingResource(this.resourceName))
      return this.$router.push({ name: '404' })

    // If this create is via a relation index, then let's grab the field
    // and use the label for that as the one we use for the title and buttons
    if (this.isRelation) {
      const { data } = await Nova.request().get(
        '/nova-api/' + this.viaResource + '/field/' + this.viaRelationship,
        {
          params: {
            resourceName: this.resourceName,
            viaResource: this.viaResource,
            viaResourceId: this.viaResourceId,
            viaRelationship: this.viaRelationship,
          },
        }
      )
      this.relationResponse = data

      if (this.isHasOneRelationship && this.alreadyFilled) {
        Nova.error(this.__('The HasOne relationship has already filled.'))

        this.$router.push({
          name: 'detail',
          params: {
            resourceId: this.viaResourceId,
            resourceName: this.viaResource,
          },
        })
      }
    }

    this.getFields()
  },

  methods: {
    /**
     * Get the available fields for the resource.
     */
    async getFields() {
      this.panels = []
      this.fields = []

      const {
        data: { panels, fields },
      } = await Nova.request().get(
        `/nova-api/${this.resourceName}/creation-fields`,
        {
          params: {
            editing: true,
            editMode: 'create',
            viaResource: this.viaResource,
            viaResourceId: this.viaResourceId,
            viaRelationship: this.viaRelationship,
          },
        }
      )

      this.panels = panels
      this.fields = fields
      this.loading = false
    },

    async submitViaCreateResource(e) {
      e.preventDefault()
      this.submittedViaCreateResource = true
      this.submittedViaCreateResourceAndAddAnother = false
      await this.createResource()
    },

    async submitViaCreateResourceAndAddAnother() {
      this.submittedViaCreateResourceAndAddAnother = true
      this.submittedViaCreateResource = false
      await this.createResource()
    },

    /**
     * Create a new resource instance using the provided data.
     */
    async createResource() {
      this.isWorking = true

      if (this.$refs.form.reportValidity()) {
        try {
          const {
            data: { redirect, id },
          } = await this.createRequest()

          Nova.success(
            this.__('The :resource was created!', {
              resource: this.resourceInformation.singularLabel.toLowerCase(),
            })
          )

          if (this.submittedViaCreateResource) {
            this.$emit('resource-created', { id, redirect })
          } else {
            // Reset the form by refetching the fields
            this.getFields()
            this.validationErrors = new Errors()
            this.submittedViaCreateAndAddAnother = false
            this.submittedViaCreateResource = false
            this.isWorking = false

            return
          }
        } catch (error) {
          this.submittedViaCreateAndAddAnother = false
          this.submittedViaCreateResource = true
          this.isWorking = false

          if (error.response.status == 422) {
            this.validationErrors = new Errors(error.response.data.errors)
            Nova.error(this.__('There was a problem submitting the form.'))
          }
        }
      }

      this.submittedViaCreateAndAddAnother = false
      this.submittedViaCreateResource = true
      this.isWorking = false
    },

    /**
     * Send a create request for this resource
     */
    createRequest() {
      return Nova.request().post(
        `/nova-api/${this.resourceName}`,
        this.createResourceFormData(),
        {
          params: {
            editing: true,
            editMode: 'create',
          },
        }
      )
    },

    /**
     * Create the form data for creating the resource.
     */
    createResourceFormData() {
      return _.tap(new FormData(), formData => {
        _.each(this.fields, field => {
          field.fill(formData)
        })

        formData.append('viaResource', this.viaResource)
        formData.append('viaResourceId', this.viaResourceId)
        formData.append('viaRelationship', this.viaRelationship)
      })
    },
  },

  computed: {
    wasSubmittedViaCreateResource() {
      return this.isWorking && this.submittedViaCreateResource
    },

    wasSubmittedViaCreateResourceAndAddAnother() {
      return this.isWorking && this.submittedViaCreateResourceAndAddAnother
    },

    panelsWithFields() {
      return _.map(this.panels, panel => {
        return {
          ...panel,
          fields: _.filter(this.fields, field => field.panel == panel.name),
        }
      })
    },

    singularName() {
      if (this.relationResponse) {
        return this.relationResponse.singularLabel
      }

      return this.resourceInformation.singularLabel
    },

    isRelation() {
      return Boolean(this.viaResourceId && this.viaRelationship)
    },

    shownViaNewRelationModal() {
      return this.mode == 'modal'
    },

    inFormMode() {
      return this.mode == 'form'
    },

    canAddMoreResources() {
      return this.authorizedToCreate
    },

    alreadyFilled() {
      return this.relationResponse && this.relationResponse.alreadyFilled
    },

    isHasOneRelationship() {
      return this.relationResponse && this.relationResponse.hasOneRelationship
    },

    shouldShowAddAnotherButton() {
      return (
        this.inFormMode && !this.alreadyFilled && !this.isHasOneRelationship
      )
    },
  },
}
</script>
