<template>
  <dropdown
    v-if="filters.length > 0 || softDeletes || !viaResource"
    dusk="filter-selector"
  >
    <dropdown-trigger
      class="bg-30 px-3 border-2 border-30 rounded"
      :class="{ 'bg-primary border-primary': filtersAreApplied }"
      :active="filtersAreApplied"
    >
      <icon
        type="filter"
        :class="filtersAreApplied ? 'text-white' : 'text-80'"
      />

      <span v-if="filtersAreApplied" class="ml-2 font-bold text-white text-80">
        {{ activeFilterCount }}
      </span>
    </dropdown-trigger>

    <dropdown-menu slot="menu" width="290" direction="rtl" :dark="true">
      <scroll-wrap :height="350">
        <div v-if="filtersAreApplied" class="bg-30 border-b border-60">
          <button
            @click="$emit('clear-selected-filters')"
            class="py-2 w-full block text-xs uppercase tracking-wide text-center text-80 dim font-bold focus:outline-none"
          >
            {{ __('Reset Filters') }}
          </button>
        </div>

        <!-- Custom Filters -->
        <component
          v-for="filter in filters"
          :resource-name="resourceName"
          :key="filter.name"
          :filter-key="filter.class"
          :is="filter.component"
          :lens="lens"
          @input="$emit('filter-changed')"
          @change="$emit('filter-changed')"
        />

        <!-- Soft Deletes -->
        <div v-if="softDeletes && showTrashedOption">
          <h3
            slot="default"
            class="text-sm uppercase tracking-wide text-80 bg-30 p-3"
          >
            {{ __('Trashed') }}
          </h3>

          <div class="p-2">
            <select
              slot="select"
              class="block w-full form-control-sm form-select"
              dusk="trashed-select"
              :value="trashed"
              @change="trashedChanged"
            >
              <option value="" selected>&mdash;</option>
              <option value="with">{{ __('With Trashed') }}</option>
              <option value="only">{{ __('Only Trashed') }}</option>
            </select>
          </div>
        </div>

        <!-- Per Page -->
        <div v-if="!viaResource">
          <h3
            slot="default"
            class="text-sm uppercase tracking-wide text-80 bg-30 p-3"
          >
            {{ __('Per Page') }}
          </h3>

          <div class="p-2">
            <select
              slot="select"
              dusk="per-page-select"
              class="block w-full form-control-sm form-select"
              :value="perPage"
              @change="perPageChanged"
            >
              <option v-for="option in perPageOptions" :key="option">
                {{ option }}
              </option>
            </select>
          </div>
        </div>
      </scroll-wrap>
    </dropdown-menu>
  </dropdown>
</template>

<script>
export default {
  props: {
    resourceName: String,
    lens: {
      type: String,
      default: '',
    },
    softDeletes: Boolean,
    viaResource: String,
    viaHasOne: Boolean,
    softDeletes: Boolean,
    trashed: {
      type: String,
      validator: value => ['', 'with', 'only'].indexOf(value) != -1,
    },
    perPage: [String, Number],
    perPageOptions: Array,
    showTrashedOption: {
      type: Boolean,
      default: true,
    },
  },

  methods: {
    trashedChanged(event) {
      this.$emit('trashed-changed', event.target.value)
    },

    perPageChanged(event) {
      this.$emit('per-page-changed', event.target.value)
    },
  },

  computed: {
    /**
     * Return the filters from state
     */
    filters() {
      return this.$store.getters[`${this.resourceName}/filters`]
    },

    /**
     * Determine via state whether filters are applied
     */
    filtersAreApplied() {
      return this.$store.getters[`${this.resourceName}/filtersAreApplied`]
    },

    /**
     * Return the number of active filters
     */
    activeFilterCount() {
      return this.$store.getters[`${this.resourceName}/activeFilterCount`]
    },
  },
}
</script>
