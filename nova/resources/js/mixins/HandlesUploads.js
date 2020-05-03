export default {
  data: () => ({ isWorking: false }),

  methods: {
    /**
     * Handle file upload finishing
     */
    handleFileUploadFinished() {
      this.isWorking = false
    },

    /**
     * Handle file upload starting
     */
    handleFileUploadStarted() {
      this.isWorking = true
    },
  },
}
