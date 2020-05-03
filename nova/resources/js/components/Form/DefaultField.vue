<template>
  <field-wrapper :stacked="field.stacked">
    <div class="w-1/5 px-8" :class="field.stacked ? 'pt-6' : 'py-6'">
      <slot>
        <form-label
          :label-for="field.attribute"
          :class="{ 'mb-2': showHelpText && field.helpText }"
        >
          {{ fieldLabel }}

          <span v-if="field.required" class="text-danger text-sm">{{
            __('*')
          }}</span>
        </form-label>
      </slot>
    </div>
    <div class="py-6 px-8" :class="fieldClasses">
      <slot name="field" />

      <help-text
        class="error-text mt-2 text-danger"
        v-if="showErrors && hasError"
      >
        {{ firstError }}
      </help-text>

      <help-text class="help-text mt-2" v-if="showHelpText">
        {{ field.helpText }}
      </help-text>
    </div>
  </field-wrapper>
</template>

<script>
import { HandlesValidationErrors, Errors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors],

  props: {
    field: { type: Object, required: true },
    fieldName: { type: String },
    showHelpText: { type: Boolean, default: true },
    showErrors: { type: Boolean, default: true },
    fullWidthContent: { type: Boolean, default: false },
  },

  computed: {
    /**
     * Return the label that should be used for the field.
     */
    fieldLabel() {
      // If the field name is purposefully an empty string, then let's show it as such
      if (this.fieldName === '') {
        return ''
      }

      return this.fieldName || this.field.name || this.field.singularLabel
    },

    /**
     * Return the classes that should be used for the field content.
     */
    fieldClasses() {
      return this.fullWidthContent
        ? this.field.stacked
          ? 'w-full'
          : 'w-4/5'
        : 'w-1/2'
    },
  },
}
</script>
