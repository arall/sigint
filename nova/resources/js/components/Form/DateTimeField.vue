<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <div class="flex items-center">
        <date-time-picker
          class="w-full form-control form-input form-input-bordered"
          :dusk="field.attribute"
          :name="field.name"
          :placeholder="placeholder"
          :dateFormat="pickerFormat"
          :value="localizedValue"
          :twelve-hour-time="usesTwelveHourTime"
          :first-day-of-week="firstDayOfWeek"
          :class="errorClasses"
          @change="handleChange"
          :disabled="isReadonly"
        />

        <span class="text-80 text-sm ml-2">({{ userTimezone }})</span>
      </div>
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

  data: () => ({ localizedValue: '' }),

  methods: {
    /*
     * Set the initial value for the field
     */
    setInitialValue() {
      // Set the initial value of the field
      this.value = this.field.value || ''

      // If the field has a value let's convert it from the app's timezone
      // into the user's local time to display in the field
      if (this.value !== '') {
        this.localizedValue = this.fromAppTimezone(this.value)
      }
    },

    /**
     * Update the field's internal value when it's value changes
     */
    handleChange(value) {
      this.value = this.toAppTimezone(value)
    },
  },

  computed: {
    firstDayOfWeek() {
      return this.field.firstDayOfWeek || 0
    },

    format() {
      return this.field.format || 'YYYY-MM-DD HH:mm:ss'
    },

    placeholder() {
      return this.field.placeholder || moment().format(this.format)
    },

    pickerFormat() {
      return this.field.pickerFormat || 'Y-m-d H:i:S'
    },
  },
}
</script>
