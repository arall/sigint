<template>
  <panel-item :field="field">
    <template slot="value">
      <excerpt :content="excerpt" :should-show="field.shouldShow" />
    </template>
  </panel-item>
</template>

<script>
const md = require('markdown-it')()

export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],

  computed: {
    excerpt() {
      return md.render(this.field.value || '')
    },
  },
}
</script>
