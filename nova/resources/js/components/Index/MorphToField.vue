<template>
  <router-link
    v-if="field.value"
    :to="{
      name: 'detail',
      params: {
        resourceName: field.resourceName,
        resourceId: field.morphToId,
      },
    }"
    class="no-underline dim text-primary font-bold"
    :class="`text-${field.textAlign}`"
  >
    {{ field.resourceLabel }}: {{ field.value }}
  </router-link>

  <span v-else>&mdash;</span>
</template>

<script>
export default {
  props: ['resourceName', 'field'],
}
</script>
