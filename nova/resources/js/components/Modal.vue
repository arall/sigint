<template>
  <div
    class="modal select-none fixed pin z-50 overflow-x-hidden overflow-y-auto"
  >
    <div class="relative mx-auto flex justify-center z-20 py-view">
      <div v-on-clickaway="close"><slot /></div>
    </div>
  </div>
</template>

<script>
import { mixin as clickaway } from 'vue-clickaway'
import composedPath from '@/polyfills/composedPath'

export default {
  mixins: [clickaway],

  props: {
    classWhitelist: [Array, String],
  },

  created() {
    document.addEventListener('keydown', this.handleEscape)
    document.body.classList.add('overflow-hidden')

    const modalBg = document.createElement('div')
    modalBg.classList = 'fixed pin bg-80 z-20 opacity-75'

    this.modalBg = modalBg

    document.body.appendChild(this.modalBg)
  },

  destroyed() {
    document.removeEventListener('keydown', this.handleEscape)
    document.body.classList.remove('overflow-hidden')
    document.body.removeChild(this.modalBg)
  },

  data: () => ({ modalBg: null }),

  methods: {
    handleEscape(e) {
      e.stopPropagation()

      if (e.keyCode == 27) {
        this.close(e)
      }
    },

    close(e) {
      if (!e.isTrusted) return

      let classArray = Array.isArray(this.classWhitelist)
        ? this.classWhitelist
        : [this.classWhitelist]

      if (
        _.filter(classArray, className => pathIncludesClass(e, className))
          .length > 0
      ) {
        return
      }

      this.$emit('modal-close', e)
    },
  },
}

function pathIncludesClass(event, className) {
  return composedPath(event)
    .filter(el => el !== document && el !== window)
    .reduce((acc, e) => acc.concat([...e.classList]), [])
    .includes(className)
}
</script>
