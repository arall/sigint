<template>
  <div>
    <template v-if="hasValue">
      <div v-if="field.asHtml" v-html="field.value"></div>
      <span v-else>{{ field.value }}</span>
    </template>
    <p v-else>&mdash;</p>
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'field'],

  computed: {
    /**
     * Determine if the field has a value other than null.
     */
    hasValue() {
      return this.field.value !== null
    },
  },
}
</script>
