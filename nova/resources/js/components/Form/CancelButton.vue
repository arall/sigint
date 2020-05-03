<template>
  <a
    @click="$emit('click')"
    tabindex="0"
    class="btn btn-link dim cursor-pointer text-80 ml-auto mr-6"
  >
    {{ __('Cancel') }}
  </a>
</template>

<script>
export default {
  //
}
</script>
