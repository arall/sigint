<template>
  <default-field :field="field" :errors="errors" :full-width-content="true">
    <template slot="field">
      <div
        class="bg-white rounded-lg overflow-hidden"
        :class="{
          'markdown-fullscreen fixed pin z-50': isFullScreen,
          'form-input form-input-bordered px-0': !isFullScreen,
          'form-control-focus': isFocused,
          'border-danger': errors.has('body'),
        }"
      >
        <header
          class="flex items-center content-center justify-between border-b border-60"
          :class="{ 'bg-30': isReadonly }"
        >
          <ul class="w-full flex items-center content-center list-reset">
            <button
              :class="{
                'text-primary font-bold': this.mode == 'write',
              }"
              @click.prevent="write"
              class="ml-1 text-90 px-3 py-2"
            >
              {{ __('Write') }}
            </button>
            <button
              :class="{
                'text-primary font-bold': this.mode == 'preview',
              }"
              @click.prevent="preview"
              class="text-90 px-3 py-2"
            >
              {{ __('Preview') }}
            </button>
          </ul>

          <ul v-if="!isReadonly" class="flex items-center list-reset">
            <button
              :key="tool.action"
              @click.prevent="callAction(tool.action)"
              v-for="tool in tools"
              class="rounded-none ico-button inline-flex items-center justify-center px-2 text-sm text-80 border-l border-60"
            >
              <component
                :is="tool.icon"
                class="fill-80 w-editor-icon h-editor-icon"
              />
            </button>
          </ul>
        </header>

        <div
          v-show="mode == 'write'"
          class="flex markdown-content relative p-4"
          :class="{ 'readonly bg-30': isReadonly }"
        >
          <textarea ref="theTextarea" :class="{ 'bg-30': isReadonly }" />
        </div>

        <div
          v-if="mode == 'preview'"
          class="markdown overflow-scroll p-4"
          v-html="previewContent"
        ></div>
      </div>
    </template>
  </default-field>
</template>

<script>
import _ from 'lodash'
const md = require('markdown-it')()
import CodeMirror from 'codemirror'
import 'codemirror/mode/markdown/markdown'
import { FormField, HandlesValidationErrors } from 'laravel-nova'

const actions = {
  bold() {
    if (!this.isEditable) return

    this.insertAround('**', '**')
  },

  italicize() {
    if (!this.isEditable) return

    this.insertAround('*', '*')
  },

  image() {
    if (!this.isEditable) return

    this.insertBefore('![](url)', 2)
  },

  link() {
    if (!this.isEditable) return

    this.insertAround('[', '](url)')
  },

  toggleFullScreen() {
    this.fullScreen = !this.fullScreen
    this.$nextTick(() => this.codemirror.refresh())
  },

  fullScreen() {
    this.fullScreen = true
  },

  exitFullScreen() {
    this.fullScreen = false
  },
}

const keyMaps = {
  'Cmd-B': 'bold',
  'Cmd-I': 'italicize',
  'Cmd-Alt-I': 'image',
  'Cmd-K': 'link',
  F11: 'fullScreen',
  Esc: 'exitFullScreen',
}

export default {
  mixins: [HandlesValidationErrors, FormField],

  data: () => ({
    fullScreen: false,
    isFocused: false,
    codemirror: null,
    mode: 'write',
    tools: [
      {
        name: 'bold',
        action: 'bold',
        className: 'fa fa-bold',
        icon: 'editor-bold',
      },
      {
        name: 'italicize',
        action: 'italicize',
        className: 'fa fa-italic',
        icon: 'editor-italic',
      },
      {
        name: 'link',
        action: 'link',
        className: 'fa fa-link',
        icon: 'editor-link',
      },
      {
        name: 'image',
        action: 'image',
        className: 'fa fa-image',
        icon: 'editor-image',
      },
      {
        name: 'fullScreen',
        action: 'toggleFullScreen',
        className: 'fa fa-expand',
        icon: 'editor-fullscreen',
      },
    ],
  }),

  mounted() {
    this.codemirror = CodeMirror.fromTextArea(this.$refs.theTextarea, {
      tabSize: 4,
      indentWithTabs: true,
      lineWrapping: true,
      mode: 'markdown',
      viewportMargin: Infinity,
      extraKeys: {
        Enter: 'newlineAndIndentContinueMarkdownList',
        ..._.map(this.tools, tool => {
          return tool.action
        }),
      },
      ...{ readOnly: this.isReadonly },
    })

    _.each(keyMaps, (action, map) => {
      const realMap = map.replace(
        'Cmd-',
        CodeMirror.keyMap['default'] == CodeMirror.keyMap.macDefault
          ? 'Cmd-'
          : 'Ctrl-'
      )
      this.codemirror.options.extraKeys[realMap] = actions[keyMaps[map]].bind(
        this
      )
    })

    this.doc.on('change', (cm, changeObj) => {
      this.value = cm.getValue()
    })

    this.codemirror.on('focus', () => (this.isFocused = true))
    this.codemirror.on('blur', () => (this.isFocused = false))

    if (this.field.value) {
      this.doc.setValue(this.field.value)
    }

    Nova.$on(this.field.attribute + '-value', value => {
      this.doc.setValue(value)
      this.$nextTick(() => this.codemirror.refresh())
    })

    this.$nextTick(() => this.codemirror.refresh())
  },

  methods: {
    focus() {
      this.codemirror.focus()
    },

    write() {
      this.mode = 'write'
      this.$nextTick(() => {
        this.codemirror.refresh()
      })
    },

    preview() {
      this.mode = 'preview'
    },

    insert(insertion) {
      this.doc.replaceRange(insertion, {
        line: this.cursor.line,
        ch: this.cursor.ch,
      })
    },

    insertAround(start, end) {
      if (this.doc.somethingSelected()) {
        const selection = this.doc.getSelection()
        this.doc.replaceSelection(start + selection + end)
      } else {
        this.doc.replaceRange(start + end, {
          line: this.cursor.line,
          ch: this.cursor.ch,
        })
        this.doc.setCursor({
          line: this.cursor.line,
          ch: this.cursor.ch - end.length,
        })
      }
    },

    insertBefore(insertion, cursorOffset) {
      if (this.doc.somethingSelected()) {
        const selects = this.doc.listSelections()
        selects.forEach(selection => {
          const pos = [selection.head.line, selection.anchor.line].sort()

          for (let i = pos[0]; i <= pos[1]; i++) {
            this.doc.replaceRange(insertion, { line: i, ch: 0 })
          }

          this.doc.setCursor({ line: pos[0], ch: cursorOffset || 0 })
        })
      } else {
        this.doc.replaceRange(insertion, {
          line: this.cursor.line,
          ch: 0,
        })
        this.doc.setCursor({
          line: this.cursor.line,
          ch: cursorOffset || 0,
        })
      }
    },

    callAction(action) {
      if (!this.isReadonly) {
        this.focus()
        actions[action].call(this)
      }
    },
  },

  computed: {
    doc() {
      return this.codemirror.getDoc()
    },

    isFullScreen() {
      return this.fullScreen == true
    },

    cursor() {
      return this.doc.getCursor()
    },

    rawContent() {
      return this.codemirror.getValue()
    },

    previewContent() {
      return md.render(this.rawContent || '')
    },

    isEditable() {
      return !this.isReadonly && this.mode == 'write'
    },
  },
}
</script>

<style src="codemirror/lib/codemirror.css" />

<style>
.ico-button {
  width: 35px;
  height: 35px;
}

.ico-button:hover {
  color: var(--primary);
}

.ico-button:active {
  color: var(--brand-80);
}

.cm-fat-cursor .CodeMirror-cursor {
  background: #000;
}

.cm-s-default .cm-header {
  color: black;
}
.cm-s-default .cm-link {
  color: var(--primary);
}
.CodeMirror-line {
  color: var(--gray-60);
}
.cm-s-default .cm-variable-2 {
  color: var(--gray-60);
}
.cm-s-default .cm-quote {
  color: var(--gray-60);
}
.cm-s-default .cm-comment {
  color: var(--gray-60);
}
.cm-s-default .cm-string {
  color: var(--gray-40);
}
.cm-s-default .cm-url {
  color: var(--gray-40);
}

.CodeMirror {
  height: auto;
  font: 14px/1.5 Menlo, Consolas, Monaco, 'Andale Mono', monospace;
  box-sizing: border-box;
  width: 100%;
}

.readonly > .CodeMirror {
  background-color: var(--30) !important;
}

.markdown-fullscreen .markdown-content {
  height: calc(100vh - 30px);
}

.markdown-fullscreen .CodeMirror {
  height: 100%;
}
</style>
