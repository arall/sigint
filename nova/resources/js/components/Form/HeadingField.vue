<template>
  <field-wrapper>
    <div v-if="shouldDisplayAsHtml" v-html="field.value" :class="classes" />
    <div v-else :class="classes">
      <p>{{ field.value }}</p>
    </div>
  </field-wrapper>
</template>
<script>
export default {
  props: {
    resourceName: {
      type: String,
      require: true,
    },
    field: {
      type: Object,
      require: true,
    },
  },

  created() {
    this.field.fill = () => {}
  },

  computed: {
    classes: () => [
      'bg-20',
      'remove-last-margin-bottom',
      'leading-normal',
      'w-full',
      'py-4',
      'px-8',
    ],

    shouldDisplayAsHtml() {
      return this.field.asHtml || false
    },
  },
}
</script>
