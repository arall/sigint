<template>
  <div :class="`text-${field.textAlign}`">
    <span v-if="field.value" class="whitespace-no-wrap">{{
      formattedDate
    }}</span>
    <span v-else>&mdash;</span>
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'field'],

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
