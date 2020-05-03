<template>
  <trix-editor
    ref="theEditor"
    @keydown.stop
    @trix-change="handleChange"
    @trix-initialize="initialize"
    @trix-attachment-add="handleAddFile"
    @trix-attachment-remove="handleRemoveFile"
    @trix-file-accept="handleFileAccept"
    :value="value"
    :placeholder="placeholder"
    class="trix-content"
  />
</template>

<script>
import Trix from 'trix'
import 'trix/dist/trix.css'

export default {
  name: 'trix-vue',

  props: {
    name: { type: String },
    value: { type: String },
    placeholder: { type: String },
    withFiles: { type: Boolean, default: true },
    disabled: { type: Boolean, default: false },
  },

  methods: {
    initialize() {
      this.$refs.theEditor.editor.insertHTML(this.value)

      if (this.disabled) {
        this.$refs.theEditor.setAttribute('contenteditable', false)
      }
    },

    handleChange() {
      this.$emit('change', this.$refs.theEditor.value)
    },

    handleFileAccept(e) {
      if (!this.withFiles) {
        e.preventDefault()
      }
    },

    handleAddFile(event) {
      this.$emit('file-add', event)
    },

    handleRemoveFile(event) {
      this.$emit('file-remove', event)
    },
  },
}
</script>
