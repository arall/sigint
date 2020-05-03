<template>
  <div :dusk="'dashboard-' + this.name">
    <custom-dashboard-header class="mb-3" :dashboard-name="name" />

    <heading v-if="cards.length > 1" class="mb-6">{{
      __('Dashboard')
    }}</heading>

    <div v-if="shouldShowCards">
      <cards v-if="smallCards.length > 0" :cards="smallCards" class="mb-3" />
      <cards v-if="largeCards.length > 0" :cards="largeCards" size="large" />
    </div>
  </div>
</template>

<script>
import { HasCards } from 'laravel-nova'

export default {
  mixins: [HasCards],

  props: {
    name: {
      type: String,
      required: false,
      default: 'main',
    },
  },

  computed: {
    /**
     * Get the endpoint for this dashboard's cards.
     */
    cardsEndpoint() {
      return `/nova-api/dashboards/${this.name}`
    },
  },
}
</script>
