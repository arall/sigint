<template>
  <label :for="labelFor" class="inline-block text-80 pt-2 leading-tight">
    <slot />
  </label>
</template>

<script>
export default {
  props: {
    labelFor: {
      type: String,
    },
  },
}
</script>
