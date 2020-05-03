import Vue from 'vue'
import store from '@/store'
import Toasted from 'vue-toasted'
import router from '@/router'
import axios from '@/util/axios'
import PortalVue from 'portal-vue'
import Loading from '@/components/Loading'
import AsyncComputed from 'vue-async-computed'
import resources from '@/store/resources'
import VTooltip from 'v-tooltip'
import Mousetrap from 'mousetrap'

Vue.use(PortalVue)
Vue.use(AsyncComputed)
Vue.use(VTooltip)

Vue.use(Toasted, {
  router,
  theme: 'nova',
  position: 'bottom-right',
  duration: 6000,
})

export default class Nova {
  constructor(config) {
    this.bus = new Vue()
    this.bootingCallbacks = []
    this.config = config
  }

  /**
   * Register a callback to be called before Nova starts. This is used to bootstrap
   * addons, tools, custom fields, or anything else Nova needs
   */
  booting(callback) {
    this.bootingCallbacks.push(callback)
  }

  /**
   * Execute all of the booting callbacks.
   */
  boot() {
    this.bootingCallbacks.forEach(callback => callback(Vue, router, store))
    this.bootingCallbacks = []
  }

  /**
   * Register the built-in Vuex modules for each resource
   */
  registerStoreModules() {
    this.config.resources.forEach(resource => {
      store.registerModule(resource.uriKey, resources)
    })
  }

  /**
   * Start the Nova app by calling each of the tool's callbacks and then creating
   * the underlying Vue instance.
   */
  liftOff() {
    let _this = this

    this.boot()
    this.registerStoreModules()

    this.app = new Vue({
      el: '#nova',
      router,
      store,
      components: { Loading },
      mounted: function () {
        this.$loading = this.$refs.loading

        _this.$on('error', message => {
          this.$toasted.show(message, { type: 'error' })
        })

        _this.$on('token-expired', () => {
          this.$toasted.show(this.__('Sorry, your session has expired.'), {
            action: {
              onClick: () => location.reload(),
              text: this.__('Reload'),
            },
            duration: null,
            type: 'error',
          })
        })
      },
    })
  }

  /**
   * Return an axios instance configured to make requests to Nova's API
   * and handle certain response codes.
   */
  request(options) {
    if (options !== undefined) {
      return axios(options)
    }

    return axios
  }

  /**
   * Register a listener on Nova's built-in event bus
   */
  $on(...args) {
    this.bus.$on(...args)
  }

  /**
   * Register a one-time listener on the event bus
   */
  $once(...args) {
    this.bus.$once(...args)
  }

  /**
   * Unregister an listener on the event bus
   */
  $off(...args) {
    this.bus.$off(...args)
  }

  /**
   * Emit an event on the event bus
   */
  $emit(...args) {
    this.bus.$emit(...args)
  }

  /**
   * Determine if Nova is missing the requested resource with the given uri key
   */
  missingResource(uriKey) {
    return _.find(this.config.resources, r => r.uriKey == uriKey) == undefined
  }

  /**
   * Show an error message to the user.
   *
   * @param {string} message
   */
  error(message) {
    Vue.toasted.show(message, { type: 'error' })
  }

  /**
   * Show a success message to the user.
   *
   * @param {string} message
   */
  success(message) {
    Vue.toasted.show(message, { type: 'success' })
  }

  /**
   * Show a warning message to the user.
   *
   * @param {string} message
   */
  warning(message) {
    Vue.toasted.show(message, { type: 'warning' })
  }

  /**
   * Register a keyboard shortcut.
   */
  addShortcut(keys, callback) {
    Mousetrap.bind(keys, callback)
  }

  /**
   * Unbind a keyboard shortcut.
   */
  removeShortcut(keys) {
    Mousetrap.unbind(keys)
  }
}
