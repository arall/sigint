<template>
  <icon
    v-if="value"
    :viewBox="viewBox"
    :width="width"
    :height="height"
    type="check-circle"
    class="text-success"
  />
  <icon
    v-else
    :viewBox="viewBox"
    :width="width"
    :height="height"
    type="x-circle"
    class="text-danger"
  />
</template>

<script>
export default {
  props: {
    value: {
      type: Boolean,
      default: false,
    },

    viewBox: {
      default: '0 0 24 24',
    },

    height: {
      default: 24,
    },

    width: {
      default: 24,
    },
  },
}
</script>
