<template>
  <select v-bind="$attrs" :value="value" v-on="inputListeners">
    <slot />
    <template v-for="(options, group) in groupedOptions">
      <optgroup :label="group" v-if="group">
        <option v-for="option in options" v-bind="attrsFor(option)"
          >{{ labelFor(option) }}
        </option>
      </optgroup>
      <template v-else>
        <option v-for="option in options" v-bind="attrsFor(option)"
          >{{ labelFor(option) }}
        </option>
      </template>
    </template>
  </select>
</template>

<script>
export default {
  props: {
    options: {
      default: [],
    },
    selected: {},
    label: {
      default: 'label',
    },
    value: {},
  },

  computed: {
    groupedOptions() {
      return _.groupBy(this.options, option => option.group || '')
    },

    inputListeners() {
      return _.assign({}, this.$listeners, {
        change: event => {
          this.$emit('input', event.target.value)
          this.$emit('change', event)
        },
        input: event => {
          this.$emit('input', event.target.value)
        },
      })
    },
  },
  methods: {
    labelFor(option) {
      return this.label instanceof Function
        ? this.label(option)
        : option[this.label]
    },

    attrsFor(option) {
      return _.assign(
        {},
        option.attrs || {},
        { value: option.value },
        this.selected !== void 0
          ? { selected: this.selected == option.value }
          : {}
      )
    },
  },
}
</script>
