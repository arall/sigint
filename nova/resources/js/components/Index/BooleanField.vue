<template>
  <div :class="`text-${field.textAlign}`">
    <boolean-icon :value="field.value" />
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'field'],
}
</script>
