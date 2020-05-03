<template>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    class="fill-current"
    :width="width"
    :height="height"
    :viewBox="viewBox"
    :aria-labelledby="type"
    role="presentation"
  >
    <component :is="iconName" />
  </svg>
</template>

<script>
export default {
  props: {
    type: {
      type: String,
      default: 'delete',
    },
    viewBox: {
      type: String,
      default: '0 0 20 20',
    },
    width: {
      type: [Number, String],
      default: 20,
    },
    height: {
      type: [Number, String],
      default: 20,
    },
  },

  computed: {
    iconName() {
      return `icon-${this.type}`
    },
  },
}
</script>
