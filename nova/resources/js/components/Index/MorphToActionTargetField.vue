<template>
  <router-link
    v-if="field.value && !isResourceBeingViewed"
    :to="{
      name: 'detail',
      params: {
        resourceName: field.resourceName,
        resourceId: field.morphToId,
      },
    }"
    class="dim no-underline text-primary font-bold"
    :class="`text-${field.textAlign}`"
  >
    {{ field.resourceLabel }}: {{ field.value }}
  </router-link>

  <span v-else> - </span>
</template>

<script>
export default {
  props: ['resourceName', 'viaResource', 'viaResourceId', 'field'],

  computed: {
    /**
     * Determine if the resource being viewed matches the field's value.
     */
    isResourceBeingViewed() {
      return (
        this.field.morphToType == this.viaResource &&
        this.field.morphToId == this.viaResourceId
      )
    },
  },
}
</script>
