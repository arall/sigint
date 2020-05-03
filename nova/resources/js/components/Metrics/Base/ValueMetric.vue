<template>
  <loading-card :loading="loading" class="px-6 py-4">
    <div class="flex mb-4">
      <h3 class="mr-3 text-base text-80 font-bold">{{ title }}</h3>

      <div v-if="helpText" class="absolute pin-r pin-b p-2 z-50">
        <tooltip trigger="click">
          <icon
            type="help"
            viewBox="0 0 17 17"
            height="16"
            width="16"
            class="cursor-pointer text-60 -mb-1"
          />

          <tooltip-content
            slot="content"
            v-html="helpText"
            :max-width="helpWidth"
          />
        </tooltip>
      </div>

      <select
        v-if="ranges.length > 0"
        @change="handleChange"
        class="select-box-sm ml-auto min-w-24 h-6 text-xs appearance-none bg-40 pl-2 pr-6 active:outline-none active:shadow-outline focus:outline-none focus:shadow-outline"
      >
        <option
          v-for="option in ranges"
          :key="option.value"
          :value="option.value"
          :selected="selectedRangeKey == option.value"
        >
          {{ option.label }}
        </option>
      </select>
    </div>

    <p class="flex items-center text-4xl mb-4">
      {{ formattedValue }}
      <span v-if="suffix" class="ml-2 text-sm font-bold text-80">{{
        formattedSuffix
      }}</span>
    </p>

    <div class="flex items-center">
      <p class="text-80 font-bold">
        <svg
          v-if="increaseOrDecreaseLabel == 'Decrease'"
          class="text-danger fill-current mr-2"
          width="20"
          height="12"
        >
          <path
            d="M2 3a1 1 0 0 0-2 0v8a1 1 0 0 0 1 1h8a1 1 0 0 0 0-2H3.414L9 4.414l3.293 3.293a1 1 0 0 0 1.414 0l6-6A1 1 0 0 0 18.293.293L13 5.586 9.707 2.293a1 1 0 0 0-1.414 0L2 8.586V3z"
          />
        </svg>
        <svg
          v-if="increaseOrDecreaseLabel == 'Increase'"
          class="rotate-180 text-success fill-current mr-2"
          width="20"
          height="12"
        >
          <path
            d="M2 3a1 1 0 0 0-2 0v8a1 1 0 0 0 1 1h8a1 1 0 0 0 0-2H3.414L9 4.414l3.293 3.293a1 1 0 0 0 1.414 0l6-6A1 1 0 0 0 18.293.293L13 5.586 9.707 2.293a1 1 0 0 0-1.414 0L2 8.586V3z"
          />
        </svg>

        <span v-if="increaseOrDecrease != 0">
          <span v-if="growthPercentage !== 0">
            {{ growthPercentage }}%
            {{ __(increaseOrDecreaseLabel) }}
          </span>

          <span v-else> {{ __('No Increase') }} </span>
        </span>

        <span v-else>
          <span v-if="previous == '0' && value != '0'">
            {{ __('No Prior Data') }}
          </span>

          <span v-if="value == '0' && previous != '0' && !zeroResult">
            {{ __('No Current Data') }}
          </span>

          <span v-if="value == '0' && previous == '0' && !zeroResult">
            {{ __('No Data') }}
          </span>
        </span>
      </p>
    </div>
  </loading-card>
</template>

<script>
import numbro from 'numbro'
import numbroLanguages from 'numbro/dist/languages.min'
Object.values(numbroLanguages).forEach(l => numbro.registerLanguage(l))
import { SingularOrPlural } from 'laravel-nova'

export default {
  name: 'BaseValueMetric',
  props: {
    loading: { default: true },
    title: {},
    helpText: {},
    helpWidth: {},
    maxWidth: {},
    previous: {},
    value: {},
    prefix: '',
    suffix: '',
    suffixInflection: {
      default: true,
    },
    selectedRangeKey: [String, Number],
    ranges: { type: Array, default: () => [] },
    format: {
      type: String,
      default: '(0[.]00a)',
    },
    zeroResult: {
      default: false,
    },
  },

  mounted() {
    if (Nova.config.locale) {
      numbro.setLanguage(Nova.config.locale.replace('_', '-'))
    }
  },

  methods: {
    handleChange(event) {
      this.$emit('selected', event.target.value)
    },
  },

  computed: {
    growthPercentage() {
      return Math.abs(this.increaseOrDecrease)
    },

    increaseOrDecrease() {
      if (this.previous == 0 || this.previous == null || this.value == 0)
        return 0

      return (((this.value - this.previous) / this.previous) * 100).toFixed(2)
    },

    increaseOrDecreaseLabel() {
      switch (Math.sign(this.increaseOrDecrease)) {
        case 1:
          return 'Increase'
        case 0:
          return 'Constant'
        case -1:
          return 'Decrease'
      }
    },

    sign() {
      switch (Math.sign(this.increaseOrDecrease)) {
        case 1:
          return '+'
        case 0:
          return ''
        case -1:
          return '-'
      }
    },

    isNullValue() {
      return this.value == null
    },

    formattedValue() {
      if (!this.isNullValue) {
        return this.prefix + numbro(new String(this.value)).format(this.format)
      }

      return ''
    },

    formattedSuffix() {
      if (this.suffixInflection === false) {
        return this.suffix
      }

      return SingularOrPlural(this.value, this.suffix)
    },
  },
}
</script>
