import Vue from 'vue'
import { shallowMount, createLocalVue } from '@vue/test-utils'
import MorphToField from '@/components/Form/MorphToField'
import flushPromises from 'flush-promises'

jest.mock('@/storage/MorphToFieldStorage')

describe('MorphToField', () => {
  /**
   * Note: This field doesn't support loading all resources initially unless we're editing or
   * coming in via a related resource because otherwise we don't know which type to load them for
   */
  test('when creating it has the correct initial state if its not searchable', async () => {
    const wrapper = shallowMount(MorphToField, {
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: '',
          morphToType: '',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: '',
        viaResourceId: '',
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(false)
    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.resourceType).toBe('')
    expect(wrapper.vm.isSearchable).toBe(false)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: '',
        current: null,
        first: false,
        search: '',
        withTrashed: false,
      },
    })
    expect(wrapper.vm.availableResources).toEqual([])
    expect(wrapper.vm.selectedResource).toEqual(null)
    expect(wrapper.vm.selectedResourceId).toBe(null)
  })

  test('when creating it has the correct initial state if it is searchable', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: true,
          morphToRelationship: 'commentable',
          morphToId: '',
          morphToType: '',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: '',
        viaResourceId: '',
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(false)
    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.resourceType).toBe('')
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: '',
        current: null,
        first: false,
        search: '',
        withTrashed: false,
      },
    })
    expect(wrapper.vm.availableResources).toEqual([])
    expect(wrapper.vm.selectedResource).toEqual(null)
    expect(wrapper.vm.selectedResourceId).toBe(null)
  })

  test('when creating via a related resource and is not searchable it loads the related type all related resources and selects the related resource', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: '',
          morphToType: '',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.resourceType).toBe('posts')
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(false)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: 'posts',
        current: 1,
        first: false,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([
      { value: 1 },
      { value: 2 },
      { value: 3 },
    ])
    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
    expect(wrapper.vm.selectedResourceId).toBe(1)
  })

  test('when creating via a related resource and it is searchable, it only loads the related type and selects the related resource', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: true,
          morphToRelationship: 'commentable',
          morphToId: '',
          morphToType: '',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.resourceType).toBe('posts')
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: 'posts',
        current: 1,
        first: true,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([{ value: 1 }])
    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
    expect(wrapper.vm.selectedResourceId).toBe(1)
  })

  test('when editing an existing resource and the field is not searchable it selects the related resource type and resource and loads all resources', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: 1,
          morphToType: 'posts',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: '',
        viaResourceId: null,
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.editingExistingResource).toBe(true)
    expect(wrapper.vm.resourceType).toBe('posts')
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(false)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: 'posts',
        current: 1,
        first: false,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([
      { value: 1 },
      { value: 2 },
      { value: 3 },
    ])
    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
    expect(wrapper.vm.selectedResourceId).toBe(1)
  })

  test('when editing an existing resource and the field is searchable it selects the related resource type and resource and doesnt load all the resources', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: true,
          morphToRelationship: 'commentable',
          morphToId: 1,
          morphToType: 'posts',
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: '',
        viaResourceId: null,
      },
    })

    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.editingExistingResource).toBe(true)
    expect(wrapper.vm.resourceType).toBe('posts')
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        type: 'posts',
        current: 1,
        first: true,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([{ value: 1 }])
    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
    expect(wrapper.vm.selectedResourceId).toBe(1)
  })

  test('it determines if its related resource soft deletes', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
          // resourceName: 'users',
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    expect(wrapper.vm.softDeletes).toBe(false)

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(true)
  })

  test('including trashed resources in the available resources can be enabled when a resource supports soft-deleting', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    wrapper.vm.enableWithTrashed()

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.withTrashed).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: 1,
        first: false,
        search: '',
        type: 'posts',
        withTrashed: true,
      },
    })
  })

  test('including trashed resources in the available resources cannot be enabled when a resource doesnt support soft-deleting', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'videos',
        viaResourceId: 1,
      },
    })

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(false)
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: 1,
        first: false,
        search: '',
        type: 'videos',
        withTrashed: false,
      },
    })
  })

  test('including trashed resources in the available resources is disabled by default', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'videos',
        viaResourceId: 1,
      },
    })

    await flushPromises()

    expect(wrapper.vm.withTrashed).toBe(false)
  })

  test('it determines if its related resource doesnt soft delete', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(true)

    wrapper.setData({ resourceType: 'videos' })
    wrapper.vm.determineIfSoftDeletes()

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(false)
  })

  test('it correctly handles filling the formData object for submit', async () => {
    const wrapper = shallowMount(MorphToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Commentable',
          attribute: 'commentable',
          searchable: false,
          morphToRelationship: 'commentable',
          morphToId: null,
          morphToType: null,
          morphToTypes: [
            {
              display: 'Post',
              type: 'App\\Nova\\Post',
              value: 'posts',
            },
            {
              display: 'Video',
              type: 'App\\Nova\\Video',
              value: 'videos',
            },
          ],
        },
        resourceName: '',
        viaRelationship: '',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    await flushPromises()

    const expectedFormData = new FormData()
    expectedFormData.append('commentable', 1)
    expectedFormData.append('commentable_type', 'posts')
    expectedFormData.append('commentable_trashed', false)

    const formData = new FormData()

    wrapper.vm.field.fill(formData)

    expect(formData).toEqual(expectedFormData)
  })
})
