<template>
  <modal @modal-close="handleClose">
    <form
      @submit.prevent="handleConfirm"
      slot-scope="props"
      class="bg-white rounded-lg shadow-lg overflow-hidden"
      style="width: 460px;"
    >
      <slot :uppercaseMode="uppercaseMode" :mode="mode">
        <div class="p-8">
          <heading :level="2" class="mb-6">{{
            __(uppercaseMode + ' Resource')
          }}</heading>
          <p class="text-80 leading-normal">
            {{
              __(
                'Are you sure you want to ' + mode + ' the selected resources?'
              )
            }}
          </p>
        </div>
      </slot>

      <div class="bg-30 px-6 py-3 flex">
        <div class="ml-auto">
          <button
            type="button"
            data-testid="cancel-button"
            dusk="cancel-delete-button"
            @click.prevent="handleClose"
            class="btn text-80 font-normal h-9 px-3 mr-3 btn-link"
          >
            {{ __('Cancel') }}
          </button>

          <button
            id="confirm-delete-button"
            ref="confirmButton"
            data-testid="confirm-button"
            type="submit"
            class="btn btn-default btn-danger"
          >
            {{ __(uppercaseMode) }}
          </button>
        </div>
      </div>
    </form>
  </modal>
</template>

<script>
export default {
  props: {
    mode: {
      type: String,
      default: 'delete',
      validator: function (value) {
        return ['force delete', 'delete', 'detach'].indexOf(value) !== -1
      },
    },
  },

  methods: {
    handleClose() {
      this.$emit('close')
    },

    handleConfirm() {
      this.$emit('confirm')
    },
  },

  /**
   * Mount the component.
   */
  mounted() {
    this.$refs.confirmButton.focus()
  },

  computed: {
    uppercaseMode() {
      return _.startCase(this.mode)
    },
  },
}
</script>
