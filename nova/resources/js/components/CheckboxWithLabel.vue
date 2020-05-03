<template>
  <label class="flex items-center select-none">
    <checkbox
      @input="$emit('input', $event)"
      :checked="checked"
      class="mr-2"
      :name="name"
      :disabled="disabled"
    />
    <slot />
  </label>
</template>

<script>
export default {
  props: {
    checked: Boolean,
    name: { type: String, required: false },
    disabled: {
      type: Boolean,
      default: false,
    },
  },
}
</script>
