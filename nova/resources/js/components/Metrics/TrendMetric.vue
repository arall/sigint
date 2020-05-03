<template>
  <BaseTrendMetric
    @selected="handleRangeSelected"
    :title="card.name"
    :help-text="card.helpText"
    :help-width="card.helpWidth"
    :value="value"
    :chart-data="data"
    :ranges="card.ranges"
    :format="format"
    :prefix="prefix"
    :suffix="suffix"
    :suffix-inflection="suffixInflection"
    :selected-range-key="selectedRangeKey"
    :loading="loading"
  />
</template>

<script>
import _ from 'lodash'
import { InteractsWithDates, Minimum } from 'laravel-nova'
import BaseTrendMetric from './Base/TrendMetric'
import MetricBehavior from './MetricBehavior'

export default {
  name: 'TrendMetric',

  mixins: [InteractsWithDates, MetricBehavior],

  components: {
    BaseTrendMetric,
  },

  props: {
    card: {
      type: Object,
      required: true,
    },

    resourceName: {
      type: String,
      default: '',
    },

    resourceId: {
      type: [Number, String],
      default: '',
    },

    lens: {
      type: String,
      default: '',
    },
  },

  data: () => ({
    loading: true,
    value: '',
    data: [],
    format: '(0[.]00a)',
    prefix: '',
    suffix: '',
    suffixInflection: true,
    selectedRangeKey: null,
  }),

  watch: {
    resourceId() {
      this.fetch()
    },
  },

  created() {
    if (this.hasRanges) {
      this.selectedRangeKey =
        this.card.selectedRangeKey || this.card.ranges[0].value
    }
  },

  mounted() {
    this.fetch()
  },

  methods: {
    handleRangeSelected(key) {
      this.selectedRangeKey = key
      this.fetch()
    },

    fetch() {
      this.loading = true

      Minimum(Nova.request().get(this.metricEndpoint, this.metricPayload)).then(
        ({
          data: {
            value: {
              labels,
              trend,
              value,
              prefix,
              suffix,
              suffixInflection,
              format,
            },
          },
        }) => {
          this.value = value
          this.labels = Object.keys(trend)
          this.data = {
            labels: Object.keys(trend),
            series: [
              _.map(trend, (value, label) => {
                return {
                  meta: label,
                  value: value,
                }
              }),
            ],
          }
          this.format = format || this.format
          this.prefix = prefix || this.prefix
          this.suffix = suffix || this.suffix
          this.suffixInflection = suffixInflection
          this.loading = false
        }
      )
    },
  },

  computed: {
    hasRanges() {
      return this.card.ranges.length > 0
    },

    metricPayload() {
      const payload = {
        params: {
          timezone: this.userTimezone,
          twelveHourTime: this.usesTwelveHourTime,
        },
      }

      if (this.hasRanges) {
        payload.params.range = this.selectedRangeKey
      }

      return payload
    },

    metricEndpoint() {
      const lens = this.lens !== '' ? `/lens/${this.lens}` : ''
      if (this.resourceName && this.resourceId) {
        return `/nova-api/${this.resourceName}${lens}/${this.resourceId}/metrics/${this.card.uriKey}`
      } else if (this.resourceName) {
        return `/nova-api/${this.resourceName}${lens}/metrics/${this.card.uriKey}`
      } else {
        return `/nova-api/metrics/${this.card.uriKey}`
      }
    },
  },
}
</script>
