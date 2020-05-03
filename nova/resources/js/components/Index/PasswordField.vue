<template>
  <div :class="`text-${field.textAlign}`">
    <span class="font-bold">
      &middot; &middot; &middot; &middot; &middot; &middot; &middot; &middot;
    </span>
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'field'],
}
</script>
