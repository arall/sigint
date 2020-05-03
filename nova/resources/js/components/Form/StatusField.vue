<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <input
        :id="field.attribute"
        :type="inputType"
        :min="inputMin"
        :max="inputMax"
        :step="inputStep"
        v-model="value"
        class="w-full form-control form-input form-input-bordered"
        :class="errorClasses"
        :placeholder="field.name"
      />
    </template>
  </default-field>
</template>

<script>
import { FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField],

  computed: {
    inputType() {
      return this.field.type || 'text'
    },

    inputStep() {
      return this.field.step
    },

    inputMin() {
      return this.field.min
    },

    inputMax() {
      return this.field.max
    },
  },
}
</script>
