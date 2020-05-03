<template>
  <panel-item :field="field">
    <p slot="value" class="text-90">
      &middot;&middot;&middot;&middot;&middot;&middot;&middot;&middot;&middot;
    </p>
  </panel-item>
</template>

<script>
export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],
}
</script>
