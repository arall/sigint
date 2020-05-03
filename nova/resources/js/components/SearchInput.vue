<template>
  <div
    :data-testid="dataTestid"
    :dusk="dataTestid"
    :class="{ 'opacity-75': disabled }"
    v-on-clickaway="close"
  >
    <div class="relative">
      <div
        ref="input"
        @click="open"
        @focus="open"
        @keydown.down.prevent="open"
        @keydown.up.prevent="open"
        :class="{
          focus: show,
          'border-danger': error,
          'form-select': shouldShowDropdownArrow,
          disabled,
        }"
        class="flex items-center form-control form-input form-input-bordered pr-6"
        :tabindex="show ? -1 : 0"
      >
        <div
          v-if="shouldShowDropdownArrow && !disabled"
          class="search-input-trigger absolute pin select-box"
        />

        <slot name="default">
          <div class="text-70">{{ __('Click to choose') }}</div>
        </slot>
      </div>

      <button
        type="button"
        @click.stop="clear"
        v-if="!shouldShowDropdownArrow && !disabled"
        tabindex="-1"
        class="absolute p-2 inline-block"
        style="right: 4px; top: 6px;"
      >
        <svg
          class="block fill-current icon h-2 w-2"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="278.046 126.846 235.908 235.908"
        >
          <path
            d="M506.784 134.017c-9.56-9.56-25.06-9.56-34.62 0L396 210.18l-76.164-76.164c-9.56-9.56-25.06-9.56-34.62 0-9.56 9.56-9.56 25.06 0 34.62L361.38 244.8l-76.164 76.165c-9.56 9.56-9.56 25.06 0 34.62 9.56 9.56 25.06 9.56 34.62 0L396 279.42l76.164 76.165c9.56 9.56 25.06 9.56 34.62 0 9.56-9.56 9.56-25.06 0-34.62L430.62 244.8l76.164-76.163c9.56-9.56 9.56-25.06 0-34.62z"
          />
        </svg>
      </button>
    </div>

    <div
      v-if="show"
      ref="dropdown"
      class="form-input px-0 border border-60 absolute pin-t pin-l my-1 overflow-hidden"
      :style="{ width: inputWidth + 'px', zIndex: 2000 }"
    >
      <div class="p-2 bg-grey-300">
        <input
          :disabled="disabled"
          v-model="search"
          @input="handleInput"
          ref="search"
          @keydown.enter.prevent="chooseSelected"
          @keydown.down.prevent="move(1)"
          @keydown.up.prevent="move(-1)"
          class="outline-none search-input-input w-full px-2 py-1.5 text-sm leading-normal bg-white rounded"
          tabindex="-1"
          type="text"
          :placeholder="__('Search')"
          spellcheck="false"
        />
      </div>

      <div
        ref="container"
        class="search-input-options relative overflow-y-scroll scrolling-touch text-sm"
        tabindex="-1"
        style="max-height: 155px;"
      >
        <div
          v-for="(option, index) in data"
          :dusk="dataTestid + '-result-' + index"
          :key="getTrackedByKey(option)"
          :ref="index === selected ? 'selected' : null"
          @click="choose(option)"
          class="px-4 py-2 cursor-pointer"
          :class="{
            [`search-input-item-${index}`]: true,
            'hover:bg-30': index !== selected,
            'bg-primary text-white': index === selected,
          }"
        >
          <slot
            name="option"
            :option="option"
            :selected="index === selected"
          ></slot>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import _ from 'lodash'
import Vue from 'vue'
import Popper from 'popper.js'
import { mixin as clickaway } from 'vue-clickaway'

export default {
  mixins: [clickaway],
  inheritAttrs: false,
  props: {
    dataTestid: {},
    disabled: { default: false },
    value: {},
    data: {},
    trackBy: {},
    searchBy: {},
    error: {
      type: Boolean,
      default: false,
    },
    boundary: {},
    debounce: {
      type: Number,
      default: 500,
    },
    clearable: {
      type: Boolean,
      default: true,
    },
  },

  data: () => ({
    show: false,
    search: '',
    selected: 0,
    popper: null,
    inputWidth: null,
  }),

  watch: {
    search(search) {
      this.selected = 0
      this.$refs.container.scrollTop = 0
    },
    show(show) {
      if (show) {
        let selected = _.findIndex(this.data, [
          this.trackBy,
          _.get(this.value, this.trackBy),
        ])
        if (selected !== -1) this.selected = selected
        this.inputWidth = this.$refs.input.offsetWidth

        Vue.nextTick(() => {
          const vm = this

          this.popper = new Popper(this.$refs.input, this.$refs.dropdown, {
            placement: 'bottom-start',
            onCreate() {
              vm.$refs.container.scrollTop = vm.$refs.container.scrollHeight
              vm.updateScrollPosition()
              vm.$refs.search.focus()
            },
            modifiers: {
              preventOverflow: {
                boundariesElement: this.boundary
                  ? this.boundary
                  : 'scrollParent',
              },
            },
          })
        })
      } else {
        if (this.popper) this.popper.destroy()
      }
    },
  },
  mounted() {
    document.addEventListener('keydown', e => {
      if (this.show && (e.keyCode == 9 || e.keyCode == 27)) {
        setTimeout(() => this.close(), 50)
      }
    })
  },

  methods: {
    getTrackedByKey(option) {
      return _.get(option, this.trackBy)
    },

    open() {
      if (!this.disabled) {
        this.show = true
        this.search = ''
      }
    },

    close() {
      this.show = false
    },

    clear() {
      if (!this.disabled) {
        this.selected = null
        this.$emit('clear', null)
      }
    },

    move(offset) {
      let newIndex = this.selected + offset

      if (newIndex >= 0 && newIndex < this.data.length) {
        this.selected = newIndex
        this.updateScrollPosition()
      }
    },

    updateScrollPosition() {
      Vue.nextTick(() => {
        if (this.$refs.selected) {
          if (
            this.$refs.selected[0].offsetTop >
            this.$refs.container.scrollTop +
              this.$refs.container.clientHeight -
              this.$refs.selected[0].clientHeight
          ) {
            this.$refs.container.scrollTop =
              this.$refs.selected[0].offsetTop +
              this.$refs.selected[0].clientHeight -
              this.$refs.container.clientHeight
          }

          if (
            this.$refs.selected[0].offsetTop < this.$refs.container.scrollTop
          ) {
            this.$refs.container.scrollTop = this.$refs.selected[0].offsetTop
          }
        }
      })
    },

    chooseSelected() {
      if (this.data[this.selected] !== undefined) {
        this.$emit('selected', this.data[this.selected])
        this.$refs.input.focus()
        Vue.nextTick(() => this.close())
      }
    },

    choose(option) {
      this.selected = _.findIndex(this.data, [
        this.trackBy,
        _.get(option, this.trackBy),
      ])
      this.$emit('selected', option)
      this.$refs.input.focus()
      Vue.nextTick(() => this.close())
    },

    /**
     * Handle the input event of the search box
     */
    handleInput(e) {
      this.debouncer(() => {
        this.$emit('input', e.target.value)
      })
    },

    /**
     * Debounce function for the input handler
     */
    debouncer: _.debounce(callback => callback(), 500),
  },

  computed: {
    shouldShowDropdownArrow() {
      return this.value == '' || this.value == null || !this.clearable
    },
  },
}
</script>
