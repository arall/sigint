import _ from 'lodash'
import { escapeUnicode } from '@/util/escapeUnicode'

export default {
  namespaced: true,

  state: () => ({
    filters: [],
    originalFilters: [],
  }),

  getters: {
    /**
     * The filters for the resource
     */
    filters: state => state.filters,

    /**
     * The original filters for the resource
     */
    originalFilters: state => state.originalFilters,

    /**
     * Determine if there are any filters for the resource.
     */
    hasFilters: state => Boolean(state.filters.length > 0),

    /**
     * The current unencoded filter value payload
     */
    currentFilters: (state, getters) => {
      return _.map(state.filters, f => {
        return {
          class: f.class,
          value: f.currentValue,
        }
      })
    },

    /**
     * Return the current filters encoded to a string.
     */
    currentEncodedFilters: (state, getters) =>
      btoa(escapeUnicode(JSON.stringify(getters.currentFilters))),

    /**
     * Determine whether any filters are applied
     */
    filtersAreApplied: (state, getters) => getters.activeFilterCount > 0,

    /**
     * Return the number of filters that are non-default
     */
    activeFilterCount: (state, getters) => {
      return _.reduce(
        state.filters,
        (result, f) => {
          const originalFilter = getters.getOriginalFilter(f.class)
          const originalFilterCloneValue = JSON.stringify(
            originalFilter.currentValue
          )
          const currentFilterCloneValue = JSON.stringify(f.currentValue)
          return currentFilterCloneValue == originalFilterCloneValue
            ? result
            : result + 1
        },
        0
      )
    },

    /**
     * Get a single filter from the list of filters.
     */
    getFilter: state => filterKey => {
      return _.find(state.filters, filter => {
        return filter.class == filterKey
      })
    },

    getOriginalFilter: state => filterKey => {
      return _.find(state.originalFilters, filter => {
        return filter.class == filterKey
      })
    },

    /**
     * Get the options for a single filter.
     */
    getOptionsForFilter: (state, getters) => filterKey => {
      const filter = getters.getFilter(filterKey)
      return filter ? filter.options : []
    },

    /**
     * Get the current value for a given filter at the provided key.
     */
    filterOptionValue: (state, getters) => (filterKey, optionKey) => {
      const filter = getters.getFilter(filterKey)

      return _.find(filter.currentValue, (value, key) => key == optionKey)
    },
  },

  actions: {
    /**
     * Fetch the current filters for the given resource name.
     */
    async fetchFilters({ commit, state }, options) {
      let { resourceName, lens = false } = options
      let { viaResource, viaResourceId, viaRelationship } = options
      let params = {
        params: {
          viaResource,
          viaResourceId,
          viaRelationship,
        },
      }

      const { data } = lens
        ? await Nova.request().get(
            '/nova-api/' + resourceName + '/lens/' + lens + '/filters',
            params
          )
        : await Nova.request().get(
            '/nova-api/' + resourceName + '/filters',
            params
          )

      commit('storeFilters', data)
    },

    /**
     * Reset the default filter state to the original filter settings.
     */
    async resetFilterState({ commit, getters }) {
      _.each(getters.originalFilters, filter => {
        commit('updateFilterState', {
          filterClass: filter.class,
          value: filter.currentValue,
        })
      })
    },

    /**
     * Initialize the current filter values from the decoded query string.
     */
    async initializeCurrentFilterValuesFromQueryString(
      { commit, getters },
      encodedFilters
    ) {
      if (encodedFilters) {
        const initialFilters = JSON.parse(atob(encodedFilters))
        _.each(initialFilters, f => {
          commit('updateFilterState', {
            filterClass: f.class,
            value: f.value,
          })
        })
      }
    },
  },

  mutations: {
    updateFilterState(state, { filterClass, value }) {
      const filter = _(state.filters).find(f => f.class == filterClass)

      filter.currentValue = value
    },

    /**
     * Store the mutable filter settings
     */
    storeFilters(state, data) {
      state.filters = data
      state.originalFilters = _.cloneDeep(data)
    },

    /**
     * Clear the filters for this resource
     */
    clearFilters(state) {
      state.filters = []
      state.originalFilters = []
    },
  },
}
