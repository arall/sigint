<script>
export default {
  props: {
    offset: {
      type: [Number, String],
      default: 3,
    },

    trigger: {
      default: 'hover',
      validator: val => ['click', 'hover'].includes(val),
    },

    placement: {
      type: String,
      default: 'top',
    },

    boundary: {
      type: String,
      default: 'window',
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
        <span>{this.$slots.default}</span>

        <template slot="popover">{this.$slots.content}</template>
      </v-popover>
    )
  },
}
</script>
