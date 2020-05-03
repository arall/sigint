<template>
  <panel-item :field="field">
    <template slot="value">
      <router-link
        v-if="field.viewable && field.value"
        :to="{
          name: 'detail',
          params: {
            resourceName: field.resourceName,
            resourceId: field.belongsToId,
          },
        }"
        class="no-underline font-bold dim text-primary"
      >
        {{ field.value }}
      </router-link>
      <p v-else-if="field.value">{{ field.value }}</p>
      <p v-else>&mdash;</p>
    </template>
  </panel-item>
</template>

<script>
export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],
}
</script>
