<template>
  <default-field :field="field" :errors="errors">
    <template slot="field">
      <input
        :id="field.attribute"
        :dusk="field.attribute"
        type="text"
        v-model="value"
        class="w-full form-control form-input form-input-bordered"
        :class="errorClasses"
        :placeholder="field.name"
        :disabled="isReadonly"
      />
    </template>
  </default-field>
</template>

<script>
import { FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField],

  /**
   * Mount the component.
   */
  mounted() {
    this.setInitialValue()

    this.field.fill = this.fill

    Nova.$on(this.field.attribute + '-value', value => {
      this.value = value
    })

    this.initializePlaces()
  },

  methods: {
    /**
     * Initialize Algolia places library.
     */
    initializePlaces() {
      const places = require('places.js')

      const placeType = this.field.placeType

      const config = {
        appId: Nova.config.algoliaAppId,
        apiKey: Nova.config.algoliaApiKey,
        container: document.querySelector('#' + this.field.attribute),
        type: this.field.placeType ? this.field.placeType : 'address',
        templates: {
          value(suggestion) {
            return suggestion.name
          },
        },
      }

      if (this.field.countries) {
        config.countries = this.field.countries
      }

      if (this.field.language) {
        config.language = this.field.language
      }

      const placesAutocomplete = places(config)

      placesAutocomplete.on('change', e => {
        this.$nextTick(() => {
          this.value = e.suggestion.name

          Nova.$emit(this.field.secondAddressLine + '-value', '')
          Nova.$emit(this.field.city + '-value', e.suggestion.city)

          Nova.$emit(
            this.field.state + '-value',
            this.parseState(
              e.suggestion.administrative,
              e.suggestion.countryCode
            )
          )

          Nova.$emit(this.field.postalCode + '-value', e.suggestion.postcode)
          Nova.$emit(this.field.suburb + '-value', e.suggestion.suburb)

          Nova.$emit(
            this.field.country + '-value',
            e.suggestion.countryCode.toUpperCase()
          )

          Nova.$emit(this.field.latitude + '-value', e.suggestion.latlng.lat)
          Nova.$emit(this.field.longitude + '-value', e.suggestion.latlng.lng)
        })
      })

      placesAutocomplete.on('clear', () => {
        this.$nextTick(() => {
          this.value = ''

          Nova.$emit(this.field.secondAddressLine + '-value', '')
          Nova.$emit(this.field.city + '-value', '')
          Nova.$emit(this.field.state + '-value', '')
          Nova.$emit(this.field.postalCode + '-value', '')
          Nova.$emit(this.field.suburb + '-value', '')
          Nova.$emit(this.field.country + '-value', '')
          Nova.$emit(this.field.latitude + '-value', '')
          Nova.$emit(this.field.longitude + '-value', '')
        })
      })
    },

    /**
     * Parse the selected state into an abbreviation if possible.
     */
    parseState(state, countryCode) {
      if (countryCode != 'us') {
        return state
      }

      return _.find(this.states, s => {
        return s.name == state
      }).abbr
    },
  },

  computed: {
    /**
     * Get the list of United States.
     */
    states() {
      return {
        AL: {
          count: '0',
          name: 'Alabama',
          abbr: 'AL',
        },
        AK: {
          count: '1',
          name: 'Alaska',
          abbr: 'AK',
        },
        AZ: {
          count: '2',
          name: 'Arizona',
          abbr: 'AZ',
        },
        AR: {
          count: '3',
          name: 'Arkansas',
          abbr: 'AR',
        },
        CA: {
          count: '4',
          name: 'California',
          abbr: 'CA',
        },
        CO: {
          count: '5',
          name: 'Colorado',
          abbr: 'CO',
        },
        CT: {
          count: '6',
          name: 'Connecticut',
          abbr: 'CT',
        },
        DE: {
          count: '7',
          name: 'Delaware',
          abbr: 'DE',
        },
        DC: {
          count: '8',
          name: 'District Of Columbia',
          abbr: 'DC',
        },
        FL: {
          count: '9',
          name: 'Florida',
          abbr: 'FL',
        },
        GA: {
          count: '10',
          name: 'Georgia',
          abbr: 'GA',
        },
        HI: {
          count: '11',
          name: 'Hawaii',
          abbr: 'HI',
        },
        ID: {
          count: '12',
          name: 'Idaho',
          abbr: 'ID',
        },
        IL: {
          count: '13',
          name: 'Illinois',
          abbr: 'IL',
        },
        IN: {
          count: '14',
          name: 'Indiana',
          abbr: 'IN',
        },
        IA: {
          count: '15',
          name: 'Iowa',
          abbr: 'IA',
        },
        KS: {
          count: '16',
          name: 'Kansas',
          abbr: 'KS',
        },
        KY: {
          count: '17',
          name: 'Kentucky',
          abbr: 'KY',
        },
        LA: {
          count: '18',
          name: 'Louisiana',
          abbr: 'LA',
        },
        ME: {
          count: '19',
          name: 'Maine',
          abbr: 'ME',
        },
        MD: {
          count: '20',
          name: 'Maryland',
          abbr: 'MD',
        },
        MA: {
          count: '21',
          name: 'Massachusetts',
          abbr: 'MA',
        },
        MI: {
          count: '22',
          name: 'Michigan',
          abbr: 'MI',
        },
        MN: {
          count: '23',
          name: 'Minnesota',
          abbr: 'MN',
        },
        MS: {
          count: '24',
          name: 'Mississippi',
          abbr: 'MS',
        },
        MO: {
          count: '25',
          name: 'Missouri',
          abbr: 'MO',
        },
        MT: {
          count: '26',
          name: 'Montana',
          abbr: 'MT',
        },
        NE: {
          count: '27',
          name: 'Nebraska',
          abbr: 'NE',
        },
        NV: {
          count: '28',
          name: 'Nevada',
          abbr: 'NV',
        },
        NH: {
          count: '29',
          name: 'New Hampshire',
          abbr: 'NH',
        },
        NJ: {
          count: '30',
          name: 'New Jersey',
          abbr: 'NJ',
        },
        NM: {
          count: '31',
          name: 'New Mexico',
          abbr: 'NM',
        },
        NY: {
          count: '32',
          name: 'New York',
          abbr: 'NY',
        },
        NC: {
          count: '33',
          name: 'North Carolina',
          abbr: 'NC',
        },
        ND: {
          count: '34',
          name: 'North Dakota',
          abbr: 'ND',
        },
        OH: {
          count: '35',
          name: 'Ohio',
          abbr: 'OH',
        },
        OK: {
          count: '36',
          name: 'Oklahoma',
          abbr: 'OK',
        },
        OR: {
          count: '37',
          name: 'Oregon',
          abbr: 'OR',
        },
        PA: {
          count: '38',
          name: 'Pennsylvania',
          abbr: 'PA',
        },
        RI: {
          count: '39',
          name: 'Rhode Island',
          abbr: 'RI',
        },
        SC: {
          count: '40',
          name: 'South Carolina',
          abbr: 'SC',
        },
        SD: {
          count: '41',
          name: 'South Dakota',
          abbr: 'SD',
        },
        TN: {
          count: '42',
          name: 'Tennessee',
          abbr: 'TN',
        },
        TX: {
          count: '43',
          name: 'Texas',
          abbr: 'TX',
        },
        UT: {
          count: '44',
          name: 'Utah',
          abbr: 'UT',
        },
        VT: {
          count: '45',
          name: 'Vermont',
          abbr: 'VT',
        },
        VA: {
          count: '46',
          name: 'Virginia',
          abbr: 'VA',
        },
        WA: {
          count: '47',
          name: 'Washington',
          abbr: 'WA',
        },
        WV: {
          count: '48',
          name: 'West Virginia',
          abbr: 'WV',
        },
        WI: {
          count: '49',
          name: 'Wisconsin',
          abbr: 'WI',
        },
        WY: {
          count: '50',
          name: 'Wyoming',
          abbr: 'WY',
        },
      }
    },
  },
}
</script>
