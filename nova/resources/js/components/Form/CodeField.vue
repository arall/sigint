<template>
  <default-field :field="field" :errors="errors" :full-width-content="true">
    <template slot="field">
      <div class="form-input form-input-bordered px-0 overflow-hidden">
        <textarea ref="theTextarea" />
      </div>
    </template>
  </default-field>
</template>

<style src="codemirror/lib/codemirror.css" />

<style src="codemirror/theme/3024-day.css" />
<style src="codemirror/theme/3024-night.css" />
<style src="codemirror/theme/abcdef.css" />
<style src="codemirror/theme/ambiance-mobile.css" />
<style src="codemirror/theme/ambiance.css" />
<style src="codemirror/theme/base16-dark.css" />
<style src="codemirror/theme/base16-light.css" />
<style src="codemirror/theme/bespin.css" />
<style src="codemirror/theme/blackboard.css" />
<style src="codemirror/theme/cobalt.css" />
<style src="codemirror/theme/colorforth.css" />
<style src="codemirror/theme/darcula.css" />
<style src="codemirror/theme/dracula.css" />
<style src="codemirror/theme/duotone-dark.css" />
<style src="codemirror/theme/duotone-light.css" />
<style src="codemirror/theme/eclipse.css" />
<style src="codemirror/theme/elegant.css" />
<style src="codemirror/theme/erlang-dark.css" />
<style src="codemirror/theme/gruvbox-dark.css" />
<style src="codemirror/theme/hopscotch.css" />
<style src="codemirror/theme/icecoder.css" />
<style src="codemirror/theme/idea.css" />
<style src="codemirror/theme/isotope.css" />
<style src="codemirror/theme/lesser-dark.css" />
<style src="codemirror/theme/liquibyte.css" />
<style src="codemirror/theme/lucario.css" />
<style src="codemirror/theme/material.css" />
<style src="codemirror/theme/mbo.css" />
<style src="codemirror/theme/mdn-like.css" />
<style src="codemirror/theme/midnight.css" />
<style src="codemirror/theme/monokai.css" />
<style src="codemirror/theme/neat.css" />
<style src="codemirror/theme/neo.css" />
<style src="codemirror/theme/night.css" />
<style src="codemirror/theme/oceanic-next.css" />
<style src="codemirror/theme/panda-syntax.css" />
<style src="codemirror/theme/paraiso-dark.css" />
<style src="codemirror/theme/paraiso-light.css" />
<style src="codemirror/theme/pastel-on-dark.css" />
<style src="codemirror/theme/railscasts.css" />
<style src="codemirror/theme/rubyblue.css" />
<style src="codemirror/theme/seti.css" />
<style src="codemirror/theme/shadowfox.css" />
<style src="codemirror/theme/solarized.css" />
<style src="codemirror/theme/ssms.css" />
<style src="codemirror/theme/the-matrix.css" />
<style src="codemirror/theme/tomorrow-night-bright.css" />
<style src="codemirror/theme/tomorrow-night-eighties.css" />
<style src="codemirror/theme/ttcn.css" />
<style src="codemirror/theme/twilight.css" />
<style src="codemirror/theme/vibrant-ink.css" />
<style src="codemirror/theme/xq-dark.css" />
<style src="codemirror/theme/xq-light.css" />
<style src="codemirror/theme/yeti.css" />
<style src="codemirror/theme/zenburn.css" />

<script>
import CodeMirror from 'codemirror'

// Modes
import 'codemirror/mode/markdown/markdown'
import 'codemirror/mode/javascript/javascript'
import 'codemirror/mode/php/php'
import 'codemirror/mode/ruby/ruby'
import 'codemirror/mode/shell/shell'
import 'codemirror/mode/sass/sass'
import 'codemirror/mode/yaml/yaml'
import 'codemirror/mode/yaml-frontmatter/yaml-frontmatter'
import 'codemirror/mode/nginx/nginx'
import 'codemirror/mode/xml/xml'
import 'codemirror/mode/vue/vue'
import 'codemirror/mode/dockerfile/dockerfile'
import 'codemirror/keymap/vim'
import 'codemirror/mode/sql/sql'
import 'codemirror/mode/twig/twig'
import 'codemirror/mode/htmlmixed/htmlmixed'

CodeMirror.defineMode('htmltwig', function (config, parserConfig) {
  return CodeMirror.overlayMode(
    CodeMirror.getMode(config, parserConfig.backdrop || 'text/html'),
    CodeMirror.getMode(config, 'twig')
  )
})

import { FormField, HandlesValidationErrors } from 'laravel-nova'

export default {
  mixins: [HandlesValidationErrors, FormField],

  data: () => ({ codemirror: null }),

  /**
   * Mount the component.
   */
  mounted() {
    const config = {
      ...{
        tabSize: 4,
        indentWithTabs: true,
        lineWrapping: true,
        lineNumbers: true,
        theme: 'dracula',
        ...{ readOnly: this.isReadonly },
      },
      ...this.field.options,
    }

    this.codemirror = CodeMirror.fromTextArea(this.$refs.theTextarea, config)

    this.doc.on('change', (cm, changeObj) => {
      this.value = cm.getValue()
    })

    this.doc.setValue(this.field.value)
    this.codemirror.setSize('100%', this.field.height)
  },

  computed: {
    doc() {
      return this.codemirror.getDoc()
    },
  },
}
</script>
