<template>
  <div>
    <dropdown class="ml-3 bg-30 hover:bg-40 rounded">
      <dropdown-trigger class="px-3">
        <icon type="delete" class="text-80" />
      </dropdown-trigger>

      <dropdown-menu slot="menu" direction="rtl" width="250">
        <div class="px-3">
          <!-- Delete Menu -->
          <button
            dusk="delete-selected-button"
            class="text-left w-full leading-normal dim my-2"
            @click="confirmDeleteSelectedResources"
            v-if="authorizedToDeleteSelectedResources || allMatchingSelected"
          >
            {{ __(viaManyToMany ? 'Detach Selected' : 'Delete Selected') }}
            ({{ selectedResourcesCount }})
          </button>

          <!-- Restore Resources -->
          <button
            dusk="restore-selected-button"
            class="text-left w-full leading-normal dim text-90 my-2"
            @click="confirmRestore"
            v-if="
              softDeletes &&
              !viaManyToMany &&
              (softDeletedResourcesSelected || allMatchingSelected) &&
              (authorizedToRestoreSelectedResources || allMatchingSelected)
            "
          >
            {{ __('Restore Selected') }} ({{ selectedResourcesCount }})
          </button>

          <!-- Force Delete Resources -->
          <button
            dusk="force-delete-selected-button"
            class="text-left w-full leading-normal dim text-90 my-2"
            @click="confirmForceDeleteSelectedResources"
            v-if="
              softDeletes &&
              !viaManyToMany &&
              (authorizedToForceDeleteSelectedResources || allMatchingSelected)
            "
          >
            {{ __('Force Delete Selected') }} ({{ selectedResourcesCount }})
          </button>
        </div>
      </dropdown-menu>
    </dropdown>

    <portal
      to="modals"
      v-if="
        deleteSelectedModalOpen ||
        forceDeleteSelectedModalOpen ||
        restoreModalOpen
      "
    >
      <delete-resource-modal
        v-if="deleteSelectedModalOpen"
        @confirm="deleteSelectedResources"
        @close="closeDeleteSelectedModal"
        :mode="viaManyToMany ? 'detach' : 'delete'"
      />

      <delete-resource-modal
        v-if="forceDeleteSelectedModalOpen"
        @confirm="forceDeleteSelectedResources"
        @close="closeForceDeleteSelectedModal"
        mode="delete"
      >
        <div slot-scope="{ uppercaseMode, mode }" class="p-8">
          <heading :level="2" class="mb-6">{{
            __('Force Delete Resource')
          }}</heading>
          <p class="text-80 leading-normal">
            {{
              __(
                'Are you sure you want to force delete the selected resources?'
              )
            }}
          </p>
        </div>
      </delete-resource-modal>

      <restore-resource-modal
        v-if="restoreModalOpen"
        @confirm="restoreSelectedResources"
        @close="closeRestoreModal"
      />
    </portal>
  </div>
</template>

<script>
export default {
  props: [
    'softDeletes',
    'resources',
    'selectedResources',
    'viaManyToMany',
    'allMatchingResourceCount',
    'allMatchingSelected',

    'authorizedToDeleteSelectedResources',
    'authorizedToForceDeleteSelectedResources',
    'authorizedToDeleteAnyResources',
    'authorizedToForceDeleteAnyResources',
    'authorizedToRestoreSelectedResources',
    'authorizedToRestoreAnyResources',
  ],

  data: () => ({
    deleteSelectedModalOpen: false,
    forceDeleteSelectedModalOpen: false,
    restoreModalOpen: false,
  }),

  /**
   * Mount the component.
   */
  mounted() {
    document.addEventListener('keydown', this.handleEscape)
  },

  /**
   * Prepare the component to tbe destroyed.
   */
  destroyed() {
    document.removeEventListener('keydown', this.handleEscape)
  },

  methods: {
    confirmDeleteSelectedResources() {
      this.deleteSelectedModalOpen = true
    },

    confirmForceDeleteSelectedResources() {
      this.forceDeleteSelectedModalOpen = true
    },

    confirmRestore() {
      this.restoreModalOpen = true
    },

    closeDeleteSelectedModal() {
      this.deleteSelectedModalOpen = false
    },

    closeForceDeleteSelectedModal() {
      this.forceDeleteSelectedModalOpen = false
    },

    closeRestoreModal() {
      this.restoreModalOpen = false
    },

    /**
     * Delete the selected resources.
     */
    deleteSelectedResources() {
      this.$emit(
        this.allMatchingSelected ? 'deleteAllMatching' : 'deleteSelected'
      )
    },

    /**
     * Force delete the selected resources.
     */
    forceDeleteSelectedResources() {
      this.$emit(
        this.allMatchingSelected
          ? 'forceDeleteAllMatching'
          : 'forceDeleteSelected'
      )
    },

    /**
     * Restore the selected resources.
     */
    restoreSelectedResources() {
      this.$emit(
        this.allMatchingSelected ? 'restoreAllMatching' : 'restoreSelected'
      )
    },

    /**
     * Handle the escape key press event.
     */
    handleEscape(e) {
      if (this.show && e.keyCode == 27) {
        this.close()
      }
    },

    /**
     * Close the modal.
     */
    close() {
      this.$emit('close')
    },
  },

  computed: {
    selectedResourcesCount() {
      return this.allMatchingSelected
        ? this.allMatchingResourceCount
        : this.selectedResources.length
    },

    /**
     * Determine if any soft deleted resources are selected.
     */
    softDeletedResourcesSelected() {
      return Boolean(
        _.find(this.selectedResources, resource => resource.softDeleted)
      )
    },
  },
}
</script>
