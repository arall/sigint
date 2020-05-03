<template>
  <div class="scroll-wrap overflow-x-hidden overflow-y-auto" :style="style">
    <slot />
  </div>
</template>

<script>
export default {
  props: {
    height: {
      type: Number,
      default: 288,
    },
  },

  computed: {
    style() {
      return {
        maxHeight: `${this.height}px`,
      }
    },
  },
}
</script>
