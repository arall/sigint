<template>
  <div>
    <h3 class="text-sm uppercase tracking-wide text-80 bg-30 p-3">
      {{ filter.name }}
    </h3>

    <div class="p-2">
      <select-control
        :dusk="`${filter.name}-filter-select`"
        class="block w-full form-control-sm form-select"
        :value="value"
        @change="handleChange"
        :options="filter.options"
        label="name"
      >
        <option value="" selected>&mdash;</option>
      </select-control>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    resourceName: {
      type: String,
      required: true,
    },
    filterKey: {
      type: String,
      required: true,
    },
    lens: String,
  },

  methods: {
    handleChange(event) {
      this.$store.commit(`${this.resourceName}/updateFilterState`, {
        filterClass: this.filterKey,
        value: event.target.value,
      })

      this.$emit('change')
    },
  },

  computed: {
    filter() {
      return this.$store.getters[`${this.resourceName}/getFilter`](
        this.filterKey
      )
    },

    value() {
      return this.filter.currentValue
    },
  },
}
</script>
