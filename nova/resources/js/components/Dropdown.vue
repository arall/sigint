<script>
export default {
  props: {
    offset: {
      type: [Number, String],
      default: 3,
    },

    trigger: {
      default: 'click',
      validator: val => ['click', 'hover'].includes(val),
    },

    placement: {
      type: String,
      default: 'bottom-start',
    },

    boundary: {
      type: String,
      default: 'viewPort',
    },
  },

  render(h) {
    return (
      <v-popover
        trigger={this.trigger}
        offset={this.offset}
        placement={this.placement}
        boundariesElement={this.boundary}
        popoverClass="z-50"
        popoverBaseClass=""
        popoverWrapperClass=""
        popoverArrowClass=""
        popoverInnerClass=""
      >
        <button
          type="button"
          staticClass="rounded active:outline-none active:shadow-outline focus:outline-none focus:shadow-outline"
        >
          {this.$slots.default}
        </button>

        <template slot="popover">{this.$slots.menu}</template>
      </v-popover>
    )
  },
}
</script>
