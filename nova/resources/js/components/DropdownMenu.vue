<template>
  <div
    ref="menu"
    :style="styles"
    class="select-none overflow-hidden bg-white border border-60 shadow rounded-lg"
  >
    <slot />
  </div>
</template>

<script>
export default {
  props: {
    width: {
      default: 120,
    },
  },

  mounted() {
    // If we recieve a click event from an anchor or button element, let's make sure
    // and close the dropdown's menu so it doesn't stay visible if we toggle a modal.
    this.$refs.menu.addEventListener('click', event => {
      if (event.target.tagName != 'A' && event.target.tagName != 'BUTTON')
        return
      Nova.$emit('close-dropdowns')
    })
  },

  computed: {
    styles() {
      return {
        width: `${this.width}px`,
      }
    },
  },
}
</script>
