<template>
  <panel-item :field="field">
    <template slot="value">
      <badge
        class="mt-1"
        :label="field.label"
        :extra-classes="field.typeClass"
      />
    </template>
  </panel-item>
</template>

<script>
import Badge from '../Badge'

export default {
  components: {
    Badge,
  },

  props: ['resource', 'resourceName', 'resourceId', 'field'],
}
</script>
