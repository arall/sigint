<template>
  <span
    class="whitespace-no-wrap px-2 py-1 rounded-full uppercase text-xs font-bold"
    :class="extraClasses"
  >
    {{ label }}
  </span>
</template>

<script>
export default {
  props: {
    label: {
      type: String,
      required: false,
    },

    extraClasses: {
      type: [Array, String],
      required: false,
    },
  },
}
</script>
