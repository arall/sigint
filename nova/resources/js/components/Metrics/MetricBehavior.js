export default {
  created() {
    Nova.$on('metric-refresh', () => {
      this.fetch()
    })

    if (this.card.refreshWhenActionRuns) {
      Nova.$on('action-executed', () => this.fetch())
    }
  },

  destroyed() {
    Nova.$off('metric-refresh')
    Nova.$off('action-executed')
  },
}
