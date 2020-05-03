<template>
  <loading-view :loading="initialLoading" :dusk="lens + '-lens-component'">
    <custom-lens-header class="mb-3" :resource-name="resourceName" />

    <div v-if="shouldShowCards">
      <cards
        v-if="smallCards.length > 0"
        :cards="smallCards"
        class="mb-3"
        :resource-name="resourceName"
        :lens="lens"
      />

      <cards
        v-if="largeCards.length > 0"
        :cards="largeCards"
        size="large"
        :resource-name="resourceName"
        :lens="lens"
      />
    </div>

    <heading v-if="resourceResponse" class="mb-3">
      <router-link
        :to="{
          name: 'index',
          params: {
            resourceName: resourceName,
          },
        }"
        class="no-underline text-primary font-bold dim"
        data-testid="lens-back"
        >&larr;</router-link
      >

      <span class="px-2 text-70">/</span> {{ resourceResponse.name }}
    </heading>

    <card>
      <div class="py-3 flex items-center border-b border-50">
        <div class="px-3" v-if="shouldShowCheckBoxes">
          <!-- Select All -->
          <dropdown
            dusk="select-all-dropdown"
            placement="bottom-end"
            class="-mx-2"
          >
            <dropdown-trigger class="px-2">
              <fake-checkbox :checked="selectAllChecked" />
            </dropdown-trigger>

            <dropdown-menu slot="menu" direction="ltr" width="250">
              <div class="p-4">
                <ul class="list-reset">
                  <li class="flex items-center mb-4">
                    <checkbox-with-label
                      :checked="selectAllChecked"
                      @input="toggleSelectAll"
                    >
                      {{ __('Select All') }}
                    </checkbox-with-label>
                  </li>
                  <li
                    class="flex items-center"
                    v-if="allMatchingResourceCount > 0"
                  >
                    <checkbox-with-label
                      dusk="select-all-matching-button"
                      :checked="selectAllMatchingChecked"
                      @input="toggleSelectAllMatching"
                    >
                      <template>
                        <span class="mr-1">
                          {{ __('Select All Matching') }} ({{
                            allMatchingResourceCount
                          }})
                        </span>
                      </template>
                    </checkbox-with-label>
                  </li>
                </ul>
              </div>
            </dropdown-menu>
          </dropdown>
        </div>

        <div class="flex items-center ml-auto px-3">
          <!-- Action Selector -->
          <action-selector
            v-if="selectedResources.length > 0"
            :resource-name="resourceName"
            :actions="actions"
            :pivot-actions="pivotActions"
            :pivot-name="pivotName"
            :selected-resources="selectedResourcesForActionSelector"
            :endpoint="lensActionEndpoint"
            :query-string="{
              currentSearch,
              encodedFilters,
              currentTrashed,
              viaResource,
              viaResourceId,
              viaRelationship,
            }"
            @actionExecuted="getResources"
          />

          <filter-menu
            :resourceName="resourceName"
            :soft-deletes="softDeletes"
            :via-resource="viaResource"
            :via-has-one="viaHasOne"
            :trashed="trashed"
            :per-page="perPage"
            :per-page-options="perPageOptions"
            :show-trashed-option="
              authorizedToForceDeleteAnyResources ||
              authorizedToRestoreAnyResources
            "
            :lens="lens"
            @clear-selected-filters="clearSelectedFilters(lens)"
            @filter-changed="filterChanged"
            @trashed-changed="trashedChanged"
            @per-page-changed="updatePerPageChanged"
          />

          <delete-menu
            v-if="shouldShowDeleteMenu"
            dusk="delete-menu"
            :soft-deletes="softDeletes"
            :resources="resources"
            :selected-resources="selectedResources"
            :via-many-to-many="viaManyToMany"
            :all-matching-resource-count="allMatchingResourceCount"
            :all-matching-selected="selectAllMatchingChecked"
            :authorized-to-delete-selected-resources="
              authorizedToDeleteSelectedResources
            "
            :authorized-to-force-delete-selected-resources="
              authorizedToForceDeleteSelectedResources
            "
            :authorized-to-delete-any-resources="authorizedToDeleteAnyResources"
            :authorized-to-force-delete-any-resources="
              authorizedToForceDeleteAnyResources
            "
            :authorized-to-restore-selected-resources="
              authorizedToRestoreSelectedResources
            "
            :authorized-to-restore-any-resources="
              authorizedToRestoreAnyResources
            "
            @deleteSelected="deleteSelectedResources"
            @deleteAllMatching="deleteAllMatchingResources"
            @forceDeleteSelected="forceDeleteSelectedResources"
            @forceDeleteAllMatching="forceDeleteAllMatchingResources"
            @restoreSelected="restoreSelectedResources"
            @restoreAllMatching="restoreAllMatchingResources"
            @close="deleteModalOpen = false"
          />
        </div>
      </div>

      <loading-view :loading="loading">
        <div
          v-if="!resources.length"
          class="flex justify-center items-center px-6 py-8"
        >
          <div class="text-center">
            <svg
              class="mb-3"
              xmlns="http://www.w3.org/2000/svg"
              width="65"
              height="51"
              viewBox="0 0 65 51"
            >
              <path
                fill="#A8B9C5"
                d="M56 40h2c.552285 0 1 .447715 1 1s-.447715 1-1 1h-2v2c0 .552285-.447715 1-1 1s-1-.447715-1-1v-2h-2c-.552285 0-1-.447715-1-1s.447715-1 1-1h2v-2c0-.552285.447715-1 1-1s1 .447715 1 1v2zm-5.364125-8H38v8h7.049375c.350333-3.528515 2.534789-6.517471 5.5865-8zm-5.5865 10H6c-3.313708 0-6-2.686292-6-6V6c0-3.313708 2.686292-6 6-6h44c3.313708 0 6 2.686292 6 6v25.049375C61.053323 31.5511 65 35.814652 65 41c0 5.522847-4.477153 10-10 10-5.185348 0-9.4489-3.946677-9.950625-9zM20 30h16v-8H20v8zm0 2v8h16v-8H20zm34-2v-8H38v8h16zM2 30h16v-8H2v8zm0 2v4c0 2.209139 1.790861 4 4 4h12v-8H2zm18-12h16v-8H20v8zm34 0v-8H38v8h16zM2 20h16v-8H2v8zm52-10V6c0-2.209139-1.790861-4-4-4H6C3.790861 2 2 3.790861 2 6v4h52zm1 39c4.418278 0 8-3.581722 8-8s-3.581722-8-8-8-8 3.581722-8 8 3.581722 8 8 8z"
              />
            </svg>

            <h3 class="text-base text-80 font-normal mb-6">
              {{
                __('No :resource matched the given criteria.', {
                  resource: resourceInformation.label.toLowerCase(),
                })
              }}
            </h3>

            <create-resource-button
              classes="btn btn-sm btn-outline"
              :singular-name="singularName"
              :resource-name="resourceName"
              :via-resource="viaResource"
              :via-resource-id="viaResourceId"
              :via-relationship="viaRelationship"
              :relationship-type="relationshipType"
              :authorized-to-create="authorizedToCreate && !resourceIsFull"
              :authorized-to-relate="authorizedToRelate"
            />
          </div>
        </div>

        <!-- Resource Table -->
        <div class="overflow-hidden overflow-x-auto relative">
          <resource-table
            :authorized-to-relate="authorizedToRelate"
            :resource-name="resourceName"
            :resources="resources"
            :singular-name="singularName"
            :selected-resources="selectedResources"
            :selected-resource-ids="selectedResourceIds"
            :actions-are-available="allActions.length > 0"
            :should-show-checkboxes="shouldShowCheckBoxes"
            :via-resource="viaResource"
            :via-resource-id="viaResourceId"
            :via-relationship="viaRelationship"
            :relationship-type="relationshipType"
            :update-selection-status="updateSelectionStatus"
            @order="orderByField"
            @delete="deleteResources"
            @restore="restoreResources"
            @actionExecuted="getResources"
            ref="resourceTable"
          />
        </div>

        <!-- Pagination -->
        <component
          :is="paginationComponent"
          v-if="resourceResponse && resources.length > 0"
          :next="hasNextPage"
          :previous="hasPreviousPage"
          @load-more="loadMore"
          @page="selectPage"
          :pages="totalPages"
          :page="currentPage"
          :per-page="perPage"
          :resource-count-label="resourceCountLabel"
          :current-resource-count="resources.length"
          :all-matching-resource-count="allMatchingResourceCount"
        >
          <span
            v-if="resourceCountLabel"
            class="text-sm text-80 px-4"
            :class="{
              'ml-auto': paginationComponent == 'pagination-links',
            }"
          >
            {{ resourceCountLabel }}
          </span>
        </component>
      </loading-view>
    </card>
  </loading-view>
</template>

<script>
import { Errors, Minimum } from 'laravel-nova'

import {
  HasCards,
  Deletable,
  Filterable,
  Paginatable,
  PerPageable,
  InteractsWithQueryString,
  InteractsWithResourceInformation,
} from 'laravel-nova'

export default {
  mixins: [
    HasCards,
    Deletable,
    Filterable,
    Paginatable,
    PerPageable,
    InteractsWithResourceInformation,
    InteractsWithQueryString,
  ],

  props: {
    resourceName: {
      type: String,
      required: true,
    },
    viaResource: {
      default: '',
    },
    viaResourceId: {
      default: '',
    },
    viaRelationship: {
      default: '',
    },
    relationshipType: {
      type: String,
      default: '',
    },
    lens: {
      type: String,
      required: true,
    },
  },

  data: () => ({
    initialLoading: true,
    loading: true,

    resourceResponse: null,
    resources: [],
    softDeletes: false,
    selectedResources: [],
    selectAllMatchingResources: false,
    allMatchingResourceCount: 0,
    hasId: false,

    deleteModalOpen: false,

    actions: [],
    pivotActions: null,
    actionValidationErrors: new Errors(),

    authorizedToRelate: false,

    orderBy: '',
    orderByDirection: '',
    trashed: '',

    // Load More Pagination
    currentPageLoadMore: null,
  }),

  /**
   * Mount the component and retrieve its initial data.
   */
  async created() {
    if (Nova.missingResource(this.resourceName))
      return this.$router.push({ name: '404' })

    this.initializeSearchFromQueryString()
    this.initializePerPageFromQueryString()
    this.initializeTrashedFromQueryString()
    this.initializeOrderingFromQueryString()

    this.perPage = this.resourceInformation.perPageOptions[0]

    await this.initializeFilters(this.lens)
    this.getResources()
    // this.getAuthorizationToRelate()
    this.getActions()

    this.initialLoading = false

    this.$watch(
      () => {
        return (
          this.lens +
          this.resourceName +
          this.encodedFilters +
          this.currentSearch +
          this.currentPage +
          this.currentPerPage +
          this.currentOrderBy +
          this.currentOrderByDirection +
          this.currentTrashed
        )
      },
      () => {
        this.getResources()
      }
    )
  },

  beforeRouteUpdate(to, from, next) {
    next()
    this.initializeState(this.lens)
  },

  methods: {
    selectAllResources() {
      this.selectedResources = this.resources.slice(0)
    },

    toggleSelectAll() {
      if (this.selectAllChecked) return this.clearResourceSelections()
      this.selectAllResources()
    },

    toggleSelectAllMatching() {
      if (!this.selectAllMatchingResources) {
        this.selectAllResources()
        this.selectAllMatchingResources = true

        return
      }

      this.selectAllMatchingResources = false
    },

    /*
     * Update the resource selection status
     */
    updateSelectionStatus(resource) {
      if (!_(this.selectedResources).includes(resource))
        return this.selectedResources.push(resource)
      const index = this.selectedResources.indexOf(resource)
      if (index > -1) return this.selectedResources.splice(index, 1)
    },

    /**
     * Get the resources based on the current page, search, filters, etc.
     */
    getResources() {
      this.loading = true

      this.$nextTick(() => {
        this.clearResourceSelections()

        return Minimum(
          Nova.request().get(
            '/nova-api/' + this.resourceName + '/lens/' + this.lens,
            {
              params: this.resourceRequestQueryString,
            }
          ),
          300
        ).then(({ data }) => {
          this.resources = []

          this.resourceResponse = data
          this.resources = data.resources
          this.softDeletes = data.softDeletes
          this.perPage = data.per_page
          this.hasId = data.hasId

          this.loading = false

          this.getAllMatchingResourceCount()

          Nova.$emit('resources-loaded')
        })
      })
    },

    /**
     * Get the actions available for the current resource.
     */
    getActions() {
      this.actions = []
      this.pivotActions = null
      Nova.request()
        .get(`/nova-api/${this.resourceName}/lens/${this.lens}/actions`, {
          params: {
            viaResource: this.viaResource,
            viaResourceId: this.viaResourceId,
            viaRelationship: this.viaRelationship,
            relationshipType: this.relationshipType,
          },
        })
        .then(response => {
          this.actions = _.filter(response.data.actions, a => a.showOnIndex)
          this.pivotActions = response.data.pivotActions
        })
    },

    /**
     * Clear the selected resouces and the "select all" states.
     */
    clearResourceSelections() {
      this.selectAllMatchingResources = false
      this.selectedResources = []
    },

    /**
     * Get the count of all of the matching resources.
     */
    getAllMatchingResourceCount() {
      Nova.request()
        .get(
          '/nova-api/' + this.resourceName + '/lens/' + this.lens + '/count',
          {
            params: this.resourceRequestQueryString,
          }
        )
        .then(response => {
          this.allMatchingResourceCount = response.data.count
        })
    },

    /**
     * Sort the resources by the given field.
     */
    orderByField(field) {
      var direction = this.currentOrderByDirection == 'asc' ? 'desc' : 'asc'
      if (this.currentOrderBy != field.attribute) {
        direction = 'asc'
      }
      this.updateQueryString({
        [this.orderByParameter]: field.attribute,
        [this.orderByDirectionParameter]: direction,
      })
    },

    /**
     * Sync the current search value from the query string.
     */
    initializeSearchFromQueryString() {
      this.search = this.currentSearch
    },

    /**
     * Sync the current order by values from the query string.
     */
    initializeOrderingFromQueryString() {
      this.orderBy = this.currentOrderBy
      this.orderByDirection = this.currentOrderByDirection
    },

    /**
     * Sync the trashed state values from the query string.
     */
    initializeTrashedFromQueryString() {
      this.trashed = this.currentTrashed
    },

    /**
     * Update the trashed constraint for the resource listing.
     */
    trashedChanged(trashedStatus) {
      this.trashed = trashedStatus
      this.updateQueryString({ [this.trashedParameter]: this.trashed })
    },

    /**
     * Update the per page parameter in the query string
     */
    updatePerPageChanged(perPage) {
      this.perPage = perPage
      this.perPageChanged()
    },

    /**
     * Load more resources.
     */
    loadMore() {
      if (this.currentPageLoadMore === null) {
        this.currentPageLoadMore = this.currentPage
      }

      this.currentPageLoadMore = this.currentPageLoadMore + 1

      return Minimum(
        Nova.request().get(
          '/nova-api/' + this.resourceName + '/lens/' + this.lens,
          {
            params: {
              ...this.resourceRequestQueryString,
              page: this.currentPageLoadMore, // We do this to override whatever page number is in the URL
            },
          }
        ),
        300
      ).then(({ data }) => {
        this.resourceResponse = data
        this.resources = [...this.resources, ...data.resources]

        this.getAllMatchingResourceCount()

        Nova.$emit('resources-loaded')
      })
    },

    /**
     * Select the next page.
     */
    selectPage(page) {
      this.updateQueryString({ [this.pageParameter]: page })
    },

    /**
     * Sync the per page values from the query string.
     */
    initializePerPageFromQueryString() {
      this.perPage =
        this.$route.query[this.perPageParameter] || _.first(this.perPageOptions)
    },
  },

  computed: {
    /**
     * Get the endpoint for this resource's actions.
     */
    lensActionEndpoint() {
      return `/nova-api/${this.resourceName}/lens/${this.lens}/action`
    },

    /**
     * Get the name of the search query string variable.
     */
    searchParameter() {
      return this.resourceName + '_search'
    },

    /**
     * Get the name of the order by query string variable.
     */
    orderByParameter() {
      return this.resourceName + '_order'
    },

    /**
     * Get the name of the order by direction query string variable.
     */
    orderByDirectionParameter() {
      return this.resourceName + '_direction'
    },

    /**
     * Get the name of the trashed constraint query string variable.
     */
    trashedParameter() {
      return this.resourceName + '_trashed'
    },

    /**
     * Get the name of the per page query string variable.
     */
    perPageParameter() {
      return this.resourceName + '_per_page'
    },

    /**
     * Get the name of the page query string variable.
     */
    pageParameter() {
      return this.resourceName + '_page'
    },

    /**
     * Build the resource request query string.
     */
    resourceRequestQueryString() {
      return {
        search: this.currentSearch,
        filters: this.encodedFilters,
        orderBy: this.currentOrderBy,
        orderByDirection: this.currentOrderByDirection,
        perPage: this.currentPerPage,
        page: this.currentPage,
        viaResource: this.viaResource,
        viaResourceId: this.viaResourceId,
        // viaRelationship: this.viaRelationship,
        viaResourceRelationship: this.viaResourceRelationship,
        relationshipType: this.relationshipType,
      }
    },

    /**
     * Determine if all resources are selected.
     */
    selectAllChecked() {
      return this.selectedResources.length == this.resources.length
    },

    /**
     * Determine if all matching resources are selected.
     */
    selectAllMatchingChecked() {
      return (
        this.selectedResources.length == this.resources.length &&
        this.selectAllMatchingResources
      )
    },

    /**
     * Get the IDs for the selected resources.
     */
    selectedResourceIds() {
      return _.map(this.selectedResources, resource => resource.id.value)
    },

    /**
     * Get all of the actions available to the resource.
     */
    allActions() {
      return this.hasPivotActions
        ? this.actions.concat(this.pivotActions.actions)
        : this.actions
    },

    /**
     * Determine if the resource has any pivot actions available.
     */
    hasPivotActions() {
      return this.pivotActions && this.pivotActions.actions.length > 0
    },

    /**
     * Determine if the resource has any actions available.
     */
    actionsAreAvailable() {
      return this.allActions.length > 0
    },

    /**
     * Get the name of the pivot model for the resource.
     */
    pivotName() {
      return this.pivotActions ? this.pivotActions.name : ''
    },

    /**
     * Get the current search value from the query string.
     */
    currentSearch() {
      return this.$route.query[this.searchParameter] || ''
    },

    /**
     * Get the current order by value from the query string.
     */
    currentOrderBy() {
      return this.$route.query[this.orderByParameter] || ''
    },

    /**
     * Get the current order by direction from the query string.
     */
    currentOrderByDirection() {
      return this.$route.query[this.orderByDirectionParameter] || 'desc'
    },

    /**
     * Get the current trashed constraint value from the query string.
     */
    currentTrashed() {
      return this.$route.query[this.trashedParameter] || ''
    },

    /**
     * Determine if the current resource listing is via a many-to-many relationship.
     */
    viaManyToMany() {
      return (
        this.relationshipType == 'belongsToMany' ||
        this.relationshipType == 'morphToMany'
      )
    },

    /**
     * Determine if the resource / relationship is "full".
     */
    resourceIsFull() {
      return this.viaHasOne && this.resources.length > 0
    },

    /**
     * Determine if the current resource listing is via a has-one relationship.
     */
    viaHasOne() {
      return (
        this.relationshipType == 'hasOne' || this.relationshipType == 'morphOne'
      )
    },

    /**
     * Get the singular name for the resource
     */
    singularName() {
      return this.resourceInformation.singularLabel
    },

    /**
     * Get the selected resources for the action selector.
     */
    selectedResourcesForActionSelector() {
      return this.selectAllMatchingChecked ? 'all' : this.selectedResourceIds
    },

    /**
     * Determine if there are any resources for the view
     */
    hasResources() {
      return Boolean(this.resources.length > 0)
    },

    /**
     * Determine if the resource should show any cards
     */
    shouldShowCards() {
      return this.cards.length > 0
    },

    /**
     * Get the endpoint for this resource's metrics.
     */
    cardsEndpoint() {
      return `/nova-api/${this.resourceName}/lens/${this.lens}/cards`
    },

    /**
     * Determine whether to show the selection checkboxes for resources
     */
    shouldShowCheckBoxes() {
      return (
        Boolean(this.hasResources && !this.viaHasOne) &&
        Boolean(
          this.actionsAreAvailable ||
            this.authorizedToDeleteAnyResources ||
            this.canShowDeleteMenu
        )
      )
    },

    /**
     * Determine whether the delete menu should be shown to the user
     */
    shouldShowDeleteMenu() {
      return (
        Boolean(this.selectedResources.length > 0) && this.canShowDeleteMenu
      )
    },

    /**
     * Determine if any selected resources may be deleted.
     */
    authorizedToDeleteSelectedResources() {
      return Boolean(
        _.find(this.selectedResources, resource => resource.authorizedToDelete)
      )
    },

    /**
     * Determine if any selected resources may be force deleted.
     */
    authorizedToForceDeleteSelectedResources() {
      return Boolean(
        _.find(
          this.selectedResources,
          resource => resource.authorizedToForceDelete
        )
      )
    },

    /**
     * Determine if the user is authorized to delete any listed resource.
     */
    authorizedToDeleteAnyResources() {
      return (
        this.resources.length > 0 &&
        Boolean(_.find(this.resources, resource => resource.authorizedToDelete))
      )
    },

    /**
     * Determine if the user is authorized to force delete any listed resource.
     */
    authorizedToForceDeleteAnyResources() {
      return (
        this.resources.length > 0 &&
        Boolean(
          _.find(this.resources, resource => resource.authorizedToForceDelete)
        )
      )
    },

    /**
     * Determine if any selected resources may be restored.
     */
    authorizedToRestoreSelectedResources() {
      return Boolean(
        _.find(this.selectedResources, resource => resource.authorizedToRestore)
      )
    },

    /**
     * Determine if the user is authorized to restore any listed resource.
     */
    authorizedToRestoreAnyResources() {
      return (
        this.resources.length > 0 &&
        Boolean(
          _.find(this.resources, resource => resource.authorizedToRestore)
        )
      )
    },

    /**
     * Determine whether the user is authorized to perform actions on the delete menu
     */
    canShowDeleteMenu() {
      return (
        this.hasId &&
        Boolean(
          this.authorizedToDeleteSelectedResources ||
            this.authorizedToForceDeleteSelectedResources ||
            this.authorizedToDeleteAnyResources ||
            this.authorizedToForceDeleteAnyResources ||
            this.authorizedToRestoreSelectedResources ||
            this.authorizedToRestoreAnyResources
        )
      )
    },

    /**
     * Return the currently encoded filter string from the store
     */
    encodedFilters() {
      return this.$store.getters[`${this.resourceName}/currentEncodedFilters`]
    },

    /**
     * Return the initial encoded filters from the query string
     */
    initialEncodedFilters() {
      return this.$route.query[this.filterParameter] || ''
    },

    paginationComponent() {
      return `pagination-${Nova.config['pagination'] || 'links'}`
    },

    hasNextPage() {
      return Boolean(
        this.resourceResponse && this.resourceResponse.next_page_url
      )
    },

    hasPreviousPage() {
      return Boolean(
        this.resourceResponse && this.resourceResponse.prev_page_url
      )
    },

    totalPages() {
      return Math.ceil(this.allMatchingResourceCount / this.currentPerPage)
    },

    /**
     * Return the resource count label
     */
    resourceCountLabel() {
      const first = this.perPage * (this.currentPage - 1)

      return (
        this.resources.length &&
        `${first + 1}-${first + this.resources.length} ${this.__('of')} ${
          this.allMatchingResourceCount
        }`
      )
    },

    /**
     * Get the current per page value from the query string.
     */
    currentPerPage() {
      return this.perPage
    },

    /**
     * The per-page options configured for this resource.
     */
    perPageOptions() {
      if (this.resourceResponse) {
        return this.resourceResponse.per_page_options
      }
    },
  },
}
</script>
