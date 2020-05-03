<template>
  <span
    @click.prevent="handleClick"
    class="cursor-pointer inline-flex items-center"
    :dusk="'sort-' + uriKey"
  >
    <slot />

    <svg
      class="ml-2 flex-no-shrink"
      xmlns="http://www.w3.org/2000/svg"
      width="8"
      height="14"
      viewBox="0 0 8 14"
    >
      <path
        :class="descClass"
        d="M1.70710678 4.70710678c-.39052429.39052429-1.02368927.39052429-1.41421356 0-.3905243-.39052429-.3905243-1.02368927 0-1.41421356l3-3c.39052429-.3905243 1.02368927-.3905243 1.41421356 0l3 3c.39052429.39052429.39052429 1.02368927 0 1.41421356-.39052429.39052429-1.02368927.39052429-1.41421356 0L4 2.41421356 1.70710678 4.70710678z"
      />
      <path
        :class="ascClass"
        d="M6.29289322 9.29289322c.39052429-.39052429 1.02368927-.39052429 1.41421356 0 .39052429.39052429.39052429 1.02368928 0 1.41421358l-3 3c-.39052429.3905243-1.02368927.3905243-1.41421356 0l-3-3c-.3905243-.3905243-.3905243-1.02368929 0-1.41421358.3905243-.39052429 1.02368927-.39052429 1.41421356 0L4 11.5857864l2.29289322-2.29289318z"
      />
    </svg>
  </span>
</template>

<script>
export default {
  props: {
    resourceName: String,
    uriKey: String,
  },

  methods: {
    /**
     * Handle the clicke event.
     */
    handleClick() {
      if (this.notSorted || this.isAscDirection) {
        this.$emit('sort', {
          key: this.uriKey,
          direction: this.direction,
        })
      }

      if (this.isDescDirection) {
        this.$emit('reset')
      }
    },
  },

  computed: {
    /**
     * Determine if the sorting direction is descending.
     */
    isDescDirection() {
      return this.direction == 'desc'
    },

    /**
     * Determine if the sorting direction is ascending.
     */
    isAscDirection() {
      return this.direction == 'asc'
    },

    /**
     * The CSS class to apply to the ascending arrow icon
     */
    ascClass() {
      if (this.isSorted && this.isDescDirection) {
        return 'fill-80'
      }

      return 'fill-60'
    },

    /**
     * The CSS class to apply to the descending arrow icon
     */
    descClass() {
      if (this.isSorted && this.isAscDirection) {
        return 'fill-80'
      }

      return 'fill-60'
    },

    /**
     * Determine whether this column is being sorted
     */
    isSorted() {
      return (
        this.sortColumn == this.uriKey &&
        ['asc', 'desc'].includes(this.direction)
      )
    },

    /**
     * The current order query parameter for this resource
     */
    sortKey() {
      return `${this.resourceName}_order`
    },

    /**
     * The current order query parameter value
     */
    sortColumn() {
      return this.$route.query[this.sortKey]
    },

    /**
     * The current direction query parameter for this resource
     */
    directionKey() {
      return `${this.resourceName}_direction`
    },

    /**
     * The current direction query parameter value
     */
    direction() {
      return this.$route.query[this.directionKey]
    },

    notSorted() {
      return !!!this.isSorted
    },
  },
}
</script>
