<template>
  <div>
    <checkbox-with-label
      class="m-2"
      :checked="isChecked"
      @input="updateCheckedState(option.value, $event.target.checked)"
    >
      {{ option.name }}
    </checkbox-with-label>
  </div>
</template>

<script>
import Checkbox from '@/components/Index/Checkbox'

export default {
  components: { Checkbox },

  props: {
    resourceName: {
      type: String,
      required: true,
    },
    filter: Object,
    option: Object,
  },

  methods: {
    updateCheckedState(optionKey, checked) {
      let oldValue = this.filter.currentValue
      let newValue = { ...oldValue, [optionKey]: checked }

      this.$store.commit(`${this.resourceName}/updateFilterState`, {
        filterClass: this.filter.class,
        value: newValue,
      })

      this.$emit('change')
    },
  },

  computed: {
    isChecked() {
      return (
        this.$store.getters[`${this.resourceName}/filterOptionValue`](
          this.filter.class,
          this.option.value
        ) == true
      )
    },
  },
}
</script>
