<template>
  <div class="bg-30 rounded-t-lg flex border-b border-50">
    <div
      class="bg-clip w-48 uppercase font-bold text-xs text-80 tracking-wide px-3 py-3"
    >
      {{ keyLabel }}
    </div>

    <div
      class="bg-clip flex-grow uppercase font-bold text-xs text-80 tracking-wide px-3 py-3 border-l border-50"
    >
      {{ valueLabel }}
    </div>
  </div>
</template>

<script>
export default {
  props: {
    keyLabel: {
      type: String,
    },
    valueLabel: {
      type: String,
    },
  },
}
</script>
