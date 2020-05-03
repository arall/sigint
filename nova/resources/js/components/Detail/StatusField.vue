<template>
  <div class="flex border-b border-40">
    <div class="w-1/4 py-4">
      <slot>
        <h4 class="font-normal text-80">{{ field.name }}</h4>
      </slot>
    </div>
    <div class="w-3/4 py-4">
      <slot name="value">
        <div class="flex items-center">
          <span
            class="mr-3 text-60"
            v-if="field.loadingWords.includes(field.value)"
          >
            <loader width="30" />
          </span>

          <p
            v-if="field.value"
            class="text-90"
            :class="{
              'text-danger': field.failedWords.includes(field.value),
            }"
          >
            {{ field.value }}
          </p>
          <p v-else>&mdash;</p>
        </div>
      </slot>
    </div>
  </div>
</template>

<script>
export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],
}
</script>
