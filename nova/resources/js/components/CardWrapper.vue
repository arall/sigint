<template>
  <div
    class="px-3 mb-6"
    :class="widthClass"
    :key="`${card.component}.${card.uriKey}`"
  >
    <component
      :class="cardSizeClass"
      :is="card.component"
      :card="card"
      :resource="resource"
      :resourceName="resourceName"
      :resourceId="resourceId"
      :lens="lens"
    />
  </div>
</template>

<script>
import { CardSizes } from 'laravel-nova'

export default {
  props: {
    card: {
      type: Object,
      required: true,
    },

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

    lens: {
      lens: String,
      default: '',
    },
  },

  computed: {
    /**
     * The class given to the card wrappers based on its width
     */
    widthClass() {
      // return 'w-full'
      // If we're passing in 'large' as the value we want to force the
      // cards to be given the `w-full` class, otherwise we're letting
      // the card decide for itself based on its configuration
      return this.size == 'large' ? 'w-full' : calculateCardWidth(this.card)
    },

    /**
     * The class given to the card based on its size
     */
    cardSizeClass() {
      return this.size !== 'large' ? 'card-panel' : ''
    },
  },
}

function calculateCardWidth(card) {
  // If the card's width is found in the accepted sizes return that class,
  // or return the default 1/3 class
  return CardSizes.indexOf(card.width) !== -1 ? `w-${card.width}` : 'w-1/3'
}
</script>
