<template>
  <card class="relative">
    <div
      v-if="loading"
      class="rounded-lg flex items-center justify-center absolute pin z-50"
      :class="modeClass"
    >
      <loader class="text-60" />
    </div>

    <slot />
  </card>
</template>

<script>
export default {
  props: {
    loading: {
      type: Boolean,
      default: true,
    },

    mode: {
      type: String,
      default: 'light',
      validator: function (value) {
        return ['light', 'dark'].indexOf(value) !== -1
      },
    },
  },

  computed: {
    modeClass() {
      return this.mode == 'light' ? 'bg-white' : 'bg-90'
    },
  },
}
</script>
