<template>
  <p>
    <img
      v-if="imageUrl"
      :src="imageUrl"
      style="object-fit: cover;"
      class="align-bottom w-8 h-8"
      :class="{ 'rounded-full': field.rounded, rounded: !field.rounded }"
    />
    <span v-else>&mdash;</span>
  </p>
</template>

<script>
export default {
  props: ['viaResource', 'viaResourceId', 'resourceName', 'field'],
  computed: {
    imageUrl() {
      if (this.field.previewUrl && !this.field.thumbnailUrl) {
        return this.field.previewUrl
      }

      return this.field.thumbnailUrl
    },
  },
}
</script>
