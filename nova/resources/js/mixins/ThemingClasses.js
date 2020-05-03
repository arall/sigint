export default {
  mounted() {
    if (this.$el && this.$el.classList !== undefined) {
      this.$el.classList.add(`nova-${_.kebabCase(this.$options.name)}`)
    }
  },
}
