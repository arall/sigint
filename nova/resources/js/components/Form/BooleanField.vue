<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <checkbox
        class="mt-2"
        @input="toggle"
        :id="field.attribute"
        :name="field.name"
        :checked="checked"
        :disabled="isReadonly"
      />
    </template>
  </default-field>
</template>

<script>
import { Errors, FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField],

  data: () => ({
    value: false,
  }),

  mounted() {
    this.value = this.field.value || false

    this.field.fill = formData => {
      formData.append(this.field.attribute, this.trueValue)
    }
  },

  methods: {
    toggle() {
      this.value = !this.value
    },
  },

  computed: {
    checked() {
      return Boolean(this.value)
    },

    trueValue() {
      return +this.checked
    },
  },
}
</script>
