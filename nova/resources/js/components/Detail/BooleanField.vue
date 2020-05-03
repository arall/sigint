<template>
  <panel-item :field="field">
    <icon
      v-if="field.value"
      slot="value"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      type="check-circle"
      class="text-success"
    />
    <icon
      v-else
      slot="value"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      type="x-circle"
      class="text-danger"
    />
  </panel-item>
</template>

<script>
export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],

  computed: {
    label() {
      return this.field.value == true ? this.__('Yes') : this.__('No')
    },
  },
}
</script>
