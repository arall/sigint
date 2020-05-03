<template>
  <div class="bg-20 rounded-b">
    <nav class="flex items-center">
      <div class="flex text-sm">
        <!-- First Link -->
        <button
          :disabled="!hasPreviousPages || linksDisabled"
          class="font-mono btn btn-link h-9 min-w-9 px-2 border-r border-50"
          :class="{
            'text-primary dim': hasPreviousPages,
            'text-80 opacity-50': !hasPreviousPages || linksDisabled,
          }"
          rel="first"
          @click.prevent="selectPage(1)"
          dusk="first"
        >
          &laquo;
        </button>

        <!-- Previous Link -->
        <button
          :disabled="!hasPreviousPages || linksDisabled"
          class="font-mono btn btn-link h-9 min-w-9 px-2 border-r border-50"
          :class="{
            'text-primary dim': hasPreviousPages,
            'text-80 opacity-50': !hasPreviousPages || linksDisabled,
          }"
          rel="prev"
          @click.prevent="selectPreviousPage()"
          dusk="previous"
        >
          &lsaquo;
        </button>

        <!-- Pages Links -->
        <button
          :disabled="linksDisabled"
          v-for="n in printPages"
          :key="n"
          class="btn btn-link h-9 min-w-9 px-2 border-r border-50"
          :class="{
            'text-primary dim': page !== n,
            'text-80 opacity-50': page === n,
          }"
          @click.prevent="selectPage(n)"
          :dusk="`page:${n}`"
        >
          {{ n }}
        </button>

        <!-- Next Link -->
        <button
          :disabled="!hasMorePages || linksDisabled"
          class="font-mono btn btn-link h-9 min-w-9 px-2 border-r border-50"
          :class="{
            'text-primary dim': hasMorePages,
            'text-80 opacity-50': !hasMorePages || linksDisabled,
          }"
          rel="next"
          @click.prevent="selectNextPage()"
          dusk="next"
        >
          &rsaquo;
        </button>

        <!-- Last Link -->
        <button
          :disabled="!hasMorePages || linksDisabled"
          class="font-mono btn btn-link h-9 min-w-9 px-2 border-r border-50"
          :class="{
            'text-primary dim': hasMorePages,
            'text-80 opacity-50': !hasMorePages || linksDisabled,
          }"
          rel="last"
          @click.prevent="selectPage(pages)"
          dusk="last"
        >
          &raquo;
        </button>
      </div>

      <slot />
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
     * Select the page.
     */
    selectPage(page) {
      if (this.page != page) {
        this.linksDisabled = true
        this.$emit('page', page)
      }
    },

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
  },

  computed: {
    /**
     * Determine if prior pages are available.
     */
    hasPreviousPages: function () {
      return this.page > 1
    },

    /**
     * Determine if more pages are available.
     */
    hasMorePages: function () {
      return this.page < this.pages
    },

    /**
     * Get printable pages.
     */
    printPages() {
      const middlePage = Math.min(Math.max(3, this.page), this.pages - 2),
        fromPage = Math.max(middlePage - 2, 1),
        toPage = Math.min(middlePage + 2, this.pages)

      let pages = []

      for (let n = fromPage; n <= toPage; ++n) {
        if (n > 0) pages.push(n)
      }

      return pages
    },
  },
}
</script>
