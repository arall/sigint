Nova.booting((Vue, router, store) => {
  Vue.component('index-{{ component }}', require('./components/IndexField'))
  Vue.component('detail-{{ component }}', require('./components/DetailField'))
  Vue.component('form-{{ component }}', require('./components/FormField'))
})
