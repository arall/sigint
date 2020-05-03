<template>
  <div class="bg-20 rounded-b">
    <nav class="flex justify-between items-center">
      <!-- Previous Link -->
      <button
        :disabled="!hasPreviousPages || linksDisabled"
        class="btn btn-link py-3 px-4"
        :class="{
          'text-primary dim': hasPreviousPages,
          'text-80 opacity-50': !hasPreviousPages || linksDisabled,
        }"
        rel="prev"
        @click.prevent="selectPreviousPage"
        dusk="previous"
      >
        {{ __('Previous') }}
      </button>

      <slot />

      <!-- Next Link -->
      <button
        :disabled="!hasMorePages || linksDisabled"
        class="btn btn-link py-3 px-4"
        :class="{
          'text-primary dim': hasMorePages,
          'text-80 opacity-50': !hasMorePages || linksDisabled,
        }"
        rel="next"
        @click.prevent="selectNextPage"
        dusk="next"
      >
        {{ __('Next') }}
      </button>
    </nav>
  </div>
</template>

<script>
export default {
  props: {
    page: {
      type: Number,
      required: true,
    },
    pages: {
      type: Number,
      default: 0,
    },
    next: {
      type: Boolean,
      default: false,
    },
    previous: {
      type: Boolean,
      default: false,
    },
  },

  data: () => ({ linksDisabled: false }),

  mounted() {
    Nova.$on('resources-loaded', () => {
      this.linksDisabled = false
    })
  },

  methods: {
    /**
     * Select the previous page.
     */
    selectPreviousPage() {
      this.selectPage(this.page - 1)
    },

    /**
     * Select the next page.
     */
    selectNextPage() {
      this.selectPage(this.page + 1)
    },

    /**
     * Select the page.
     */
    selectPage(page) {
      this.linksDisabled = true
      this.$emit('page', page)
    },
  },

  computed: {
    /**
     * Determine if prior pages are available.
     */
    hasPreviousPages: function () {
      return this.previous
    },

    /**
     * Determine if more pages are available.
     */
    hasMorePages: function () {
      return this.next
    },
  },
}
</script>
