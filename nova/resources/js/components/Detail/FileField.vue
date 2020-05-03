<template>
  <panel-item :field="field">
    <div slot="value">
      <template v-if="shouldShowLoader">
        <ImageLoader
          :src="imageUrl"
          :maxWidth="maxWidth"
          :rounded="rounded"
          @missing="value => (missing = value)"
        />
      </template>

      <template v-if="field.value && !imageUrl">
        <span class="break-words">{{ field.value }}</span>
      </template>

      <span v-if="!field.value && !imageUrl">&mdash;</span>

      <p v-if="shouldShowToolbar" class="flex items-center text-sm mt-3">
        <a
          v-if="field.downloadable"
          :dusk="field.attribute + '-download-link'"
          @keydown.enter.prevent="download"
          @click.prevent="download"
          tabindex="0"
          class="cursor-pointer dim btn btn-link text-primary inline-flex items-center"
        >
          <icon
            class="mr-2"
            type="download"
            view-box="0 0 24 24"
            width="16"
            height="16"
          />
          <span class="class mt-1">{{ __('Download') }}</span>
        </a>
      </p>
    </div>
  </panel-item>
</template>

<script>
import ImageLoader from '@/components/ImageLoader'

export default {
  props: ['resource', 'resourceName', 'resourceId', 'field'],

  components: { ImageLoader },

  data: () => ({ missing: false }),

  methods: {
    /**
     * Download the linked file
     */
    download() {
      const { resourceName, resourceId } = this
      const attribute = this.field.attribute

      let link = document.createElement('a')
      link.href = `/nova-api/${resourceName}/${resourceId}/download/${attribute}`
      link.download = 'download'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    },
  },

  computed: {
    hasValue() {
      return (
        Boolean(this.field.value || this.imageUrl) && !Boolean(this.missing)
      )
    },

    shouldShowLoader() {
      return Boolean(this.imageUrl)
    },

    shouldShowToolbar() {
      return Boolean(this.field.downloadable && this.hasValue)
    },

    imageUrl() {
      return this.field.previewUrl || this.field.thumbnailUrl
    },

    rounded() {
      return this.field.rounded
    },

    maxWidth() {
      return this.field.maxWidth || 320
    },

    isVaporField() {
      return this.field.component == 'vapor-file-field'
    },
  },
}
</script>
