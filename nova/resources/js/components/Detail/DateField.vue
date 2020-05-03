<template>
  <panel-item :field="field">
    <template slot="value">
      <p v-if="field.value" class="text-90">{{ formattedDate }}</p>
      <p v-else>&mdash;</p>
    </template>
  </panel-item>
</template>

<script>
export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],

  computed: {
    formattedDate() {
      if (this.field.format) {
        return moment(this.field.value).format(this.field.format)
      }

      return this.field.value
    },
  },
}
</script>
