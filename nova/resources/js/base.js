module.exports = {
  methods: {
    /**
     * Translate the given key.
     */
    __(key, replace) {
      var translation = window.config.translations[key]
        ? window.config.translations[key]
        : key

      _.forEach(replace, (value, key) => {
        translation = translation.replace(':' + key, value)
      })

      return translation
    },
  },
}
