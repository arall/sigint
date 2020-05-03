<template>
  <div v-if="panel.fields.length > 0">
    <heading :level="1" :class="panel.helpText ? 'mb-2' : 'mb-3'">{{
      panel.name
    }}</heading>

    <p
      v-if="panel.helpText"
      class="text-80 text-sm font-semibold italic mb-3"
      v-html="panel.helpText"
    ></p>

    <card>
      <component
        :class="{
          'remove-bottom-border': index == panel.fields.length - 1,
        }"
        v-for="(field, index) in panel.fields"
        :key="index"
        :is="`${mode}-${field.component}`"
        :errors="validationErrors"
        :resource-id="resourceId"
        :resource-name="resourceName"
        :field="field"
        :via-resource="viaResource"
        :via-resource-id="viaResourceId"
        :via-relationship="viaRelationship"
        :shown-via-new-relation-modal="shownViaNewRelationModal"
        @file-deleted="$emit('update-last-retrieved-at-timestamp')"
        @file-upload-started="$emit('file-upload-started')"
        @file-upload-finished="$emit('file-upload-finished')"
      />
    </card>
  </div>
</template>

<script>
export default {
  name: 'FormPanel',

  props: {
    shownViaNewRelationModal: {
      type: Boolean,
      default: false,
    },

    panel: {
      type: Object,
      required: true,
    },

    name: {
      default: 'Panel',
    },

    mode: {
      type: String,
      default: 'form',
    },

    fields: {
      type: Array,
      default: [],
    },

    validationErrors: {
      type: Object,
      required: true,
    },

    resourceName: {
      type: String,
      required: true,
    },

    resourceId: {
      type: [Number, String],
    },

    viaResource: {
      type: String,
    },

    viaResourceId: {
      type: [Number, String],
    },

    viaRelationship: {
      type: String,
    },
  },
}
</script>
