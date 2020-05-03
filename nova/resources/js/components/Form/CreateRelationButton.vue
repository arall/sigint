<template>
  <button
    @click="$emit('click')"
    type="button"
    class="rounded dim font-bold text-sm text-primary inline-flex items-center focus:outline-none active:outline-none focus:shadow-outline active:shadow-outline"
  >
    <icon type="add" width="24" height="24" view-box="0 0 24 24" />
    <span>{{ __('Create') }}</span>
  </button>
</template>

<script>
export default {
  //
}
</script>
