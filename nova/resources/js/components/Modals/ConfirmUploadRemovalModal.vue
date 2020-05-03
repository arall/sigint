<template>
  <modal @modal-close="handleClose">
    <div
      class="bg-white rounded-lg shadow-lg overflow-hidden"
      style="width: 460px;"
    >
      <div class="p-8">
        <heading :level="2" class="mb-6">{{ __('Delete File') }}</heading>
        <p class="text-80">
          {{ __('Are you sure you want to delete this file?') }}
        </p>
      </div>

      <div class="bg-30 px-6 py-3 flex">
        <div class="ml-auto">
          <button
            dusk="cancel-upload-delete-button"
            type="button"
            @click.prevent="handleClose"
            class="btn text-80 font-normal h-9 px-3 mr-3 btn-link"
          >
            {{ __('Cancel') }}
          </button>

          <progress-button
            @click.prevent.native="handleConfirm"
            ref="confirmButton"
            dusk="confirm-upload-delete-button"
            :disabled="clicked"
            :processing="clicked"
            class="btn-danger"
          >
            {{ __('Delete') }}
          </progress-button>
        </div>
      </div>
    </div>
  </modal>
</template>

<script>
export default {
  /**
   * Mount the component.
   */
  mounted() {
    this.$refs.confirmButton.focus()
  },

  data: () => ({ clicked: false }),

  methods: {
    handleClose() {
      this.$emit('close')
    },

    handleConfirm() {
      this.clicked = true
      this.$emit('confirm')
    },
  },
}
</script>
