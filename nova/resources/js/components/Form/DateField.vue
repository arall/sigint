<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <date-time-picker
        :dusk="field.attribute"
        class="w-full form-control form-input form-input-bordered"
        :name="field.name"
        :value="value"
        :dateFormat="pickerFormat"
        :placeholder="placeholder"
        :enable-time="false"
        :enable-seconds="false"
        :first-day-of-week="firstDayOfWeek"
        :class="errorClasses"
        @change="handleChange"
        :disabled="isReadonly"
      />
    </template>
  </default-field>
</template>

<script>
import {
  Errors,
  FormField,
  HandlesValidationErrors,
  InteractsWithDates,
} from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField, InteractsWithDates],

  computed: {
    firstDayOfWeek() {
      return this.field.firstDayOfWeek || 0
    },

    placeholder() {
      return this.field.placeholder || moment().format(this.format)
    },

    format() {
      return this.field.format || 'YYYY-MM-DD'
    },

    pickerFormat() {
      return this.field.pickerFormat || 'Y-m-d'
    },
  },
}
</script>
