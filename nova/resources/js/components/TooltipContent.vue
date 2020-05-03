<script>
const defaultClasses =
  'bg-white px-3 py-2 rounded border border-50 shadow text-sm leading-normal'

export default {
  props: {
    maxWidth: {
      default: 'auto',
    },
  },

  render(h) {
    return (
      <div
        class={this.$props.class || defaultClasses}
        style={`max-width: ${this.maxWidth}px`}
      >
        {this.$slots.default}
      </div>
    )
  },
}
</script>
