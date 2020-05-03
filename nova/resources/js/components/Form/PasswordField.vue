<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <input
        :id="field.attribute"
        :dusk="field.attribute"
        type="password"
        v-model="value"
        class="w-full form-control form-input form-input-bordered"
        :class="errorClasses"
        :placeholder="field.name"
        autocomplete="new-password"
        :disabled="isReadonly"
      />
    </template>
  </default-field>
</template>

<script>
import { FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField],
}
</script>
