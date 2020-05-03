<template>
  <checkbox :checked="checked" :disabled="true" class="pointer-events-none" />
</template>

<script>
export default {
  props: {
    checked: {
      default: false,
    },
  },
}
</script>
