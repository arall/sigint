<template>
  <div v-if="shouldShowButtons">
    <!-- Attach Related Models -->
    <router-link
      v-if="shouldShowAttachButton"
      dusk="attach-button"
      :class="classes"
      :to="{
        name: 'attach',
        params: {
          resourceName: viaResource,
          resourceId: viaResourceId,
          relatedResourceName: resourceName,
        },
        query: {
          viaRelationship: viaRelationship,
          polymorphic: relationshipType == 'morphToMany' ? '1' : '0',
        },
      }"
    >
      <slot> {{ __('Attach :resource', { resource: singularName }) }}</slot>
    </router-link>

    <!-- Create Related Models -->
    <router-link
      v-else-if="shouldShowCreateButton"
      dusk="create-button"
      :class="classes"
      :to="{
        name: 'create',
        params: {
          resourceName: resourceName,
        },
        query: {
          viaResource: viaResource,
          viaResourceId: viaResourceId,
          viaRelationship: viaRelationship,
        },
      }"
    >
      {{ __('Create :resource', { resource: singularName }) }}
    </router-link>
  </div>
</template>

<script>
export default {
  props: {
    classes: { default: 'btn btn-default btn-primary' },
    singularName: {},
    resourceName: {},
    viaResource: {},
    viaResourceId: {},
    viaRelationship: {},
    relationshipType: {},
    authorizedToCreate: {},
    authorizedToRelate: {},
  },

  computed: {
    /**
     * Determine if any buttons should be displayed.
     */
    shouldShowButtons() {
      return this.shouldShowAttachButton || this.shouldShowCreateButton
    },

    /**
     * Determine if the attach button should be displayed.
     */
    shouldShowAttachButton() {
      return (
        (this.relationshipType == 'belongsToMany' ||
          this.relationshipType == 'morphToMany') &&
        this.authorizedToRelate
      )
    },

    /**
     * Determine if the create button should be displayed.
     */
    shouldShowCreateButton() {
      return this.authorizedToCreate && this.authorizedToRelate
    },
  },
}
</script>
