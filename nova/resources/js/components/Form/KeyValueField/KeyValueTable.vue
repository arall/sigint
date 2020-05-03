<template>
  <div
    class="relative rounded-lg rounded-b-lg bg-30 bg-clip border border-60"
    :class="{ 'mr-11': editMode && deleteRowEnabled }"
  >
    <slot />
  </div>
</template>

<script>
export default {
  props: {
    deleteRowEnabled: {
      type: Boolean,
      default: true,
    },
    editMode: {
      type: Boolean,
      default: true,
    },
  },
}
</script>
