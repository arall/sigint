<template>
  <panel-item :field="field">
    <template slot="value">
      <router-link
        :to="{
          name: 'detail',
          params: {
            resourceName: field.resourceName,
            resourceId: field.morphToId,
          },
        }"
        class="no-underline font-bold dim text-primary"
      >
        {{ field.name }}: {{ field.value }} ({{ field.resourceLabel }})
      </router-link>
    </template>
  </panel-item>
</template>

<script>
export default {
  props: ['resourceName', 'resourceId', 'field'],
}
</script>
