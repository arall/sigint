/**
 * First we will load all of this project's JavaScript dependencies which
 * includes Vue and other libraries. It is a great starting point when
 * building robust, powerful web applications using Vue and Laravel.
 */
import Vue from 'vue'
import Nova from './Nova'
import './plugins'
import Localization from '@/mixins/Localization'
import ThemingClasses from '@/mixins/ThemingClasses'

Vue.config.productionTip = false

Vue.mixin(Localization)

/**
 * If configured, register a global mixin to add theming-friendly CSS
 * classnames to Nova's built-in Vue components. This allows the user
 * to fully customize Nova's theme to their project's branding.
 */
if (window.config.themingClasses) {
  Vue.mixin(ThemingClasses)
}

/**
 * Next, we'll setup some of Nova's Vue components that need to be global
 * so that they are always available. Then, we will be ready to create
 * the actual Vue instance and start up this JavaScript application.
 */
import './fields'
import './components'

/**
 * Finally, we'll create this Vue Router instance and register all of the
 * Nova routes. Once that is complete, we will create the Vue instance
 * and hand this router to the Vue instance. Then Nova is all ready!
 */
;(function () {
  this.CreateNova = function (config) {
    return new Nova(config)
  }
}.call(window))
