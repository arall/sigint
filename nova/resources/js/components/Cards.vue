<template>
  <div v-if="filteredCards.length > 0" class="flex flex-wrap -mx-3">
    <card-wrapper
      v-for="card in filteredCards"
      :card="card"
      :size="size"
      :resource="resource"
      :resource-name="resourceName"
      :resource-id="resourceId"
      :key="`${card.component}.${card.uriKey}`"
      :lens="lens"
    />
  </div>
</template>

<script>
export default {
  props: {
    cards: Array,

    size: {
      type: String,
      default: '',
    },

    resource: {
      type: Object,
    },

    resourceName: {
      type: String,
    },

    resourceId: {
      type: [Number, String],
    },

    onlyOnDetail: {
      type: Boolean,
      default: false,
    },

    lens: {
      lens: String,
      default: '',
    },
  },

  computed: {
    /**
     * Determine whether to show the cards based on their onlyOnDetail configuration
     */
    filteredCards() {
      if (this.onlyOnDetail) {
        return _.filter(this.cards, c => c.onlyOnDetail == true)
      }

      return _.filter(this.cards, c => c.onlyOnDetail == false)
    },
  },
}
</script>
