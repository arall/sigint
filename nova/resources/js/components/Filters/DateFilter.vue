<template>
  <div>
    <h3 class="text-sm uppercase tracking-wide text-80 bg-30 p-3">
      {{ filter.name }}
    </h3>

    <div class="p-2">
      <date-time-picker
        class="w-full form-control form-input form-input-bordered"
        dusk="date-filter"
        name="date-filter"
        autocomplete="off"
        :value="value"
        dateFormat="Y-m-d"
        :placeholder="placeholder"
        :enable-time="false"
        :enable-seconds="false"
        :first-day-of-week="firstDayOfWeek"
        @input.prevent=""
        @change="handleChange"
      />
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
    handleChange(value) {
      this.$store.commit(`${this.resourceName}/updateFilterState`, {
        filterClass: this.filterKey,
        value,
      })
      this.$emit('change')
    },
  },

  computed: {
    placeholder() {
      return this.filter.placeholder || this.__('Choose date')
    },

    value() {
      return this.filter.currentValue
    },

    filter() {
      return this.$store.getters[`${this.resourceName}/getFilter`](
        this.filterKey
      )
    },

    options() {
      return this.$store.getters[`${this.resourceName}/getOptionsForFilter`](
        this.filterKey
      )
    },

    firstDayOfWeek() {
      return this.filter.firstDayOfWeek || 0
    },
  },
}
</script>
