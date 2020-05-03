<template>
  <div class="relative" :class="{ 'overflow-hidden': loading }">
    <div
      v-if="loading"
      class="flex items-center justify-center z-50 p-6"
      style="min-height: 150px;"
    >
      <loader class="text-60" />
    </div>

    <slot v-else />
  </div>
</template>

<script>
export default {
  props: {
    loading: {
      type: Boolean,
      default: true,
    },
  },
}
</script>
