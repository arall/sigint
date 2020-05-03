<template>
  <loading-card
    ref="card"
    :loading="loading"
    class="card relative border border-lg border-50 overflow-hidden px-0 py-0"
    :class="cardClasses"
    :style="cardStyles"
  >
    <div class="missing p-8" v-if="missing">
      <p class="text-center leading-normal">
        <a :href="src" class="text-primary dim" target="_blank">{{
          __('This image')
        }}</a>
        {{ __('could not be found.') }}
      </p>
    </div>
  </loading-card>
</template>

<script>
import { Minimum } from 'laravel-nova'

export default {
  props: {
    src: String,

    maxWidth: {
      type: Number,
      default: 320,
    },

    rounded: {
      type: Boolean,
      default: false,
    },
  },

  data: () => ({
    loading: true,
    missing: false,
  }),

  computed: {
    cardClasses() {
      return {
        'max-w-xs': !this.maxWidth || this.loading || this.missing,
        'rounded-full': this.rounded,
      }
    },

    cardStyles() {
      return this.loading
        ? { height: this.maxWidth + 'px', width: this.maxWidth + 'px' }
        : null
    },
  },

  mounted() {
    Minimum(
      new Promise((resolve, reject) => {
        let image = new Image()

        image.addEventListener('load', () => resolve(image))
        image.addEventListener('error', () => reject())

        image.src = this.src
      })
    )
      .then(image => {
        image.className = 'block w-full'
        image.draggable = false

        if (this.maxWidth) {
          this.$refs.card.$el.style.maxWidth = `${this.maxWidth}px`
        }

        this.$refs.card.$el.appendChild(image)
      })
      .catch(() => {
        this.missing = true

        this.$emit('missing', true)
      })
      .finally(() => {
        this.loading = false
      })
  },
}
</script>

<style scoped>
.card {
  padding: 0 !important;
}
</style>
