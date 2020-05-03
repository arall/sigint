<template>
  <div class="hidden" :errors="errors">
    <input type="hidden" :value="value" />
  </div>
</template>

<script>
import { FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [FormField, HandlesValidationErrors],
}
</script>
