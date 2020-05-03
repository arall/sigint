<template>
  <div><badge :label="field.label" :extra-classes="field.typeClass" /></div>
</template>

<script>
import Badge from '../Badge'

export default {
  components: {
    Badge,
  },

  props: ['resourceName', 'viaResource', 'viaResourceId', 'field'],
}
</script>
