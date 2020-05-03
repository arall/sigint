<template>
  <modal
    dusk="new-relation-modal"
    tabindex="-1"
    role="dialog"
    @modal-close="handleClose"
    :classWhitelist="[
      'flatpickr-current-month',
      'flatpickr-next-month',
      'flatpickr-prev-month',
      'flatpickr-weekday',
      'flatpickr-weekdays',
      'flatpickr-calendar',
    ]"
  >
    <div
      class="bg-40 rounded-lg shadow-lg overflow-hidden p-8"
      style="width: 800px;"
    >
      <Create
        mode="modal"
        @refresh="handleRefresh"
        @cancelled-create="handleCancelledCreate"
        :resource-name="resourceName"
        resource-id=""
        via-resource=""
        via-resource-id=""
        via-relationship=""
      />
    </div>
  </modal>
</template>

<script>
import Create from '@/views/Create'

export default {
  components: { Create },

  props: {
    resourceName: {},
    resourceId: {},
    viaResource: {},
    viaResourceId: {},
    viaRelationship: {},
  },

  created() {
    console.log('created', this.resourceName)
  },

  mounted() {
    console.log('mounted', this.resourceName)
  },

  methods: {
    handleRefresh(data) {
      // alert('wew refreshing')
      this.$emit('set-resource', data)
    },

    handleCancelledCreate() {
      return this.$emit('cancelled-create')
    },

    /**
     * Close the modal.
     */
    handleClose() {
      this.$emit('cancelled-create')
    },
  },
}
</script>
