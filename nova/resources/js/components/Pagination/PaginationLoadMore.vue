<template>
  <div class="bg-20 p-3 text-center rounded-b flex justify-between">
    <p class="leading-normal text-sm text-80">{{ resourceCountLabel }}</p>

    <p v-if="allResourcesLoaded" class="leading-normal text-sm text-80">
      {{ __('All resources loaded.') }}
    </p>

    <button
      v-else
      @click="loadMore"
      class="btn btn btn-link px-4 text-primary dim"
    >
      {{ buttonLabel }}
    </button>

    <p class="leading-normal text-sm text-80">
      {{ __(':amount Total', { amount: allMatchingResourceCount }) }}
    </p>
  </div>
</template>

<script>
export default {
  props: {
    currentResourceCount: {
      type: Number,
      required: true,
    },
    allMatchingResourceCount: {
      type: Number,
      required: true,
    },
    resourceCountLabel: {
      type: String,
      required: true,
    },
    perPage: {
      type: [Number, String],
      required: true,
    },
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

  methods: {
    loadMore() {
      this.$emit('load-more')
    },
  },

  computed: {
    buttonLabel() {
      return this.__('Load :perPage More', { perPage: this.perPage })
    },

    allResourcesLoaded() {
      return this.currentResourceCount == this.allMatchingResourceCount
    },
  },
}
</script>
