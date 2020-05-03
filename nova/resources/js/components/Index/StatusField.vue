<template>
  <div class="flex items-center">
    <span class="mr-3 text-60" v-if="field.loadingWords.includes(field.value)">
      <loader width="30" />
    </span>

    <span :class="{ 'text-danger': field.failedWords.includes(field.value) }">
      {{ field.value }}
    </span>
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'field'],
}
</script>
