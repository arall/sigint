<template>
  <loading-view :loading="initialLoading">
    <custom-detail-header
      class="mb-3"
      :resource="resource"
      :resource-id="resourceId"
      :resource-name="resourceName"
    />

    <div v-if="shouldShowCards">
      <cards
        v-if="smallCards.length > 0"
        :cards="smallCards"
        class="mb-3"
        :resource="resource"
        :resource-id="resourceId"
        :resource-name="resourceName"
        :only-on-detail="true"
      />

      <cards
        v-if="largeCards.length > 0"
        :cards="largeCards"
        size="large"
        :resource="resource"
        :resource-id="resourceId"
        :resource-name="resourceName"
        :only-on-detail="true"
      />
    </div>

    <!-- Resource Detail -->
    <div
      v-for="panel in availablePanels"
      :dusk="resourceName + '-detail-component'"
      class="mb-8"
      :key="panel.id"
    >
      <component
        :is="panel.component"
        :resource-name="resourceName"
        :resource-id="resourceId"
        :resource="resource"
        :panel="panel"
      >
        <div v-if="panel.showToolbar" class="flex items-center mb-3">
          <heading :level="1" class="flex-no-shrink">{{ panel.name }}</heading>

          <div class="ml-3 w-full flex items-center">
            <custom-detail-toolbar
              :resource="resource"
              :resource-name="resourceName"
              :resource-id="resourceId"
            />

            <!-- Actions -->
            <action-selector
              v-if="resource"
              :resource-name="resourceName"
              :actions="actions"
              :pivot-actions="{ actions: [] }"
              :selected-resources="selectedResources"
              :query-string="{
                currentSearch,
                encodedFilters,
                currentTrashed,
                viaResource,
                viaResourceId,
                viaRelationship,
              }"
              @actionExecuted="actionExecuted"
              class="ml-3"
            />

            <button
              v-if="resource.authorizedToDelete && !resource.softDeleted"
              data-testid="open-delete-modal"
              dusk="open-delete-modal-button"
              @click="openDeleteModal"
              class="btn btn-default btn-icon btn-white mr-3"
              :title="__('Delete')"
            >
              <icon type="delete" class="text-80" />
            </button>

            <button
              v-if="resource.authorizedToRestore && resource.softDeleted"
              data-testid="open-restore-modal"
              dusk="open-restore-modal-button"
              @click="openRestoreModal"
              class="btn btn-default btn-icon btn-white mr-3"
              :title="__('Restore')"
            >
              <icon type="restore" class="text-80" />
            </button>

            <button
              v-if="resource.authorizedToForceDelete"
              data-testid="open-force-delete-modal"
              dusk="open-force-delete-modal-button"
              @click="openForceDeleteModal"
              class="btn btn-default btn-icon btn-white mr-3"
              :title="__('Force Delete')"
            >
              <icon type="force-delete" class="text-80" />
            </button>

            <portal
              to="modals"
              v-if="deleteModalOpen || restoreModalOpen || forceDeleteModalOpen"
            >
              <delete-resource-modal
                v-if="deleteModalOpen"
                @confirm="confirmDelete"
                @close="closeDeleteModal"
                mode="delete"
              />

              <restore-resource-modal
                v-if="restoreModalOpen"
                @confirm="confirmRestore"
                @close="closeRestoreModal"
              />

              <delete-resource-modal
                v-if="forceDeleteModalOpen"
                @confirm="confirmForceDelete"
                @close="closeForceDeleteModal"
                mode="force delete"
              />
            </portal>

            <router-link
              v-if="resource.authorizedToUpdate"
              data-testid="edit-resource"
              dusk="edit-resource-button"
              :to="{ name: 'edit', params: { id: resource.id } }"
              class="btn btn-default btn-icon bg-primary"
              :title="__('Edit')"
            >
              <icon
                type="edit"
                class="text-white"
                style="margin-top: -2px; margin-left: 3px;"
              />
            </router-link>
          </div>
        </div>
      </component>
    </div>
  </loading-view>
</template>

<script>
import {
  InteractsWithResourceInformation,
  Errors,
  Deletable,
  Minimum,
  HasCards,
} from 'laravel-nova'

export default {
  props: ['resourceName', 'resourceId'],

  mixins: [Deletable, HasCards, InteractsWithResourceInformation],

  data: () => ({
    initialLoading: true,
    loading: true,

    resource: null,
    panels: [],
    actions: [],
    actionValidationErrors: new Errors(),
    deleteModalOpen: false,
    restoreModalOpen: false,
    forceDeleteModalOpen: false,
  }),

  watch: {
    resourceId: function (newResourceId, oldResourceId) {
      if (newResourceId != oldResourceId) {
        this.initializeComponent()
      }
    },
  },

  /**
   * Bind the keydown even listener when the component is created
   */
  created() {
    if (Nova.missingResource(this.resourceName))
      return this.$router.push({ name: '404' })

    document.addEventListener('keydown', this.handleKeydown)
  },

  /**
   * Unbind the keydown even listener when the component is destroyed
   */
  destroyed() {
    document.removeEventListener('keydown', this.handleKeydown)
  },

  /**
   * Mount the component.
   */
  mounted() {
    this.initializeComponent()
  },

  methods: {
    /**
     * Handle the keydown event
     */
    handleKeydown(e) {
      if (
        this.resource.authorizedToUpdate &&
        !e.ctrlKey &&
        !e.altKey &&
        !e.metaKey &&
        !e.shiftKey &&
        e.keyCode == 69 &&
        e.target.tagName != 'INPUT' &&
        e.target.tagName != 'TEXTAREA'
      ) {
        this.$router.push({
          name: 'edit',
          params: { id: this.resource.id },
        })
      }
    },

    /**
     * Initialize the compnent's data.
     */
    async initializeComponent() {
      await this.getResource()
      await this.getActions()

      this.initialLoading = false
    },

    /**
     * Get the resource information.
     */
    getResource() {
      this.resource = null

      return Minimum(
        Nova.request().get(
          '/nova-api/' + this.resourceName + '/' + this.resourceId
        )
      )
        .then(({ data: { panels, resource } }) => {
          this.panels = panels
          this.resource = resource
          this.loading = false
        })
        .catch(error => {
          if (error.response.status >= 500) {
            Nova.$emit('error', error.response.data.message)
            return
          }

          if (error.response.status === 404 && this.initialLoading) {
            this.$router.push({ name: '404' })
            return
          }

          if (error.response.status === 403) {
            this.$router.push({ name: '403' })
            return
          }

          Nova.error(this.__('This resource no longer exists'))

          this.$router.push({
            name: 'index',
            params: { resourceName: this.resourceName },
          })
        })
    },

    /**
     * Get the available actions for the resource.
     */
    getActions() {
      this.actions = []

      return Nova.request()
        .get('/nova-api/' + this.resourceName + '/actions', {
          params: {
            resourceId: this.resourceId,
          },
        })
        .then(response => {
          this.actions = _.filter(response.data.actions, a => a.showOnDetail)
        })
    },

    /**
     * Handle an action executed event.
     */
    async actionExecuted() {
      await this.getResource()
      await this.getActions()
    },

    /**
     * Create a new panel for the given field.
     */
    createPanelForField(field) {
      return _.tap(
        _.find(this.panels, panel => panel.name == field.panel),
        panel => {
          panel.fields = [field]
        }
      )
    },

    /**
     * Create a new panel for the given relationship field.
     */
    createPanelForRelationship(field) {
      return {
        component: 'relationship-panel',
        prefixComponent: true,
        name: field.name,
        fields: [field],
      }
    },

    /**
     * Show the confirmation modal for deleting or detaching a resource
     */
    async confirmDelete() {
      this.deleteResources([this.resource], () => {
        Nova.success(
          this.__('The :resource was deleted!', {
            resource: this.resourceInformation.singularLabel.toLowerCase(),
          })
        )

        if (!this.resource.softDeletes) {
          this.$router.push({
            name: 'index',
            params: { resourceName: this.resourceName },
          })
          return
        }

        this.closeDeleteModal()
        this.getResource()
      })
    },

    /**
     * Open the delete modal
     */
    openDeleteModal() {
      this.deleteModalOpen = true
    },

    /**
     * Close the delete modal
     */
    closeDeleteModal() {
      this.deleteModalOpen = false
    },

    /**
     * Show the confirmation modal for restoring a resource
     */
    async confirmRestore() {
      this.restoreResources([this.resource], () => {
        Nova.success(
          this.__('The :resource was restored!', {
            resource: this.resourceInformation.singularLabel.toLowerCase(),
          })
        )

        this.closeRestoreModal()
        this.getResource()
      })
    },

    /**
     * Open the restore modal
     */
    openRestoreModal() {
      this.restoreModalOpen = true
    },

    /**
     * Close the restore modal
     */
    closeRestoreModal() {
      this.restoreModalOpen = false
    },

    /**
     * Show the confirmation modal for force deleting
     */
    async confirmForceDelete() {
      this.forceDeleteResources([this.resource], () => {
        Nova.success(
          this.__('The :resource was deleted!', {
            resource: this.resourceInformation.singularLabel.toLowerCase(),
          })
        )

        this.$router.push({
          name: 'index',
          params: { resourceName: this.resourceName },
        })
      })
    },

    /**
     * Open the force delete modal
     */
    openForceDeleteModal() {
      this.forceDeleteModalOpen = true
    },

    /**
     * Close the force delete modal
     */
    closeForceDeleteModal() {
      this.forceDeleteModalOpen = false
    },
  },

  computed: {
    /**
     * Get the available field panels.
     */
    availablePanels() {
      if (this.resource) {
        var panels = {}

        var fields = _.toArray(JSON.parse(JSON.stringify(this.resource.fields)))

        fields.forEach(field => {
          if (field.listable) {
            return (panels[field.name] = this.createPanelForRelationship(field))
          } else if (panels[field.panel]) {
            return panels[field.panel].fields.push(field)
          }

          panels[field.panel] = this.createPanelForField(field)
        })

        return _.toArray(panels)
      }
    },

    /**
     * These are here to satisfy the parameter requirements for deleting the resource
     */
    currentSearch() {
      return ''
    },

    encodedFilters() {
      return []
    },

    currentTrashed() {
      return ''
    },

    viaResource() {
      return ''
    },

    viaResourceId() {
      return ''
    },

    viaRelationship() {
      return ''
    },

    selectedResources() {
      return [this.resourceId]
    },

    /**
     * Determine whether this is a detail view for an Action Event
     */
    isActionDetail() {
      return this.resourceName == 'action-events'
    },

    /**
     * Get the endpoint for this resource's metrics.
     */
    cardsEndpoint() {
      return `/nova-api/${this.resourceName}/cards`
    },

    /**
     * Get the extra card params to pass to the endpoint.
     */
    extraCardParams() {
      return {
        resourceId: this.resourceId,
      }
    },
  },
}
</script>
