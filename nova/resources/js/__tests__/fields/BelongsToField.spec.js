import { shallowMount } from '@vue/test-utils'
import BelongsToField from '@/components/Form/BelongsToField'
import flushPromises from 'flush-promises'

jest.mock('@/storage/BelongsToFieldStorage')

describe('BelongsToField', () => {
  test('when creating it fetches all resources on mount if the field is not searchable', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: '',
          attribute: 'user',
          searchable: false,
          resourceName: 'users',
        },
        resourceName: 'posts',
        viaResource: '',
        viaResourceId: '',
      },
    })

    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.selectedResourceId).toBe(null)
    expect(wrapper.vm.isSearchable).toBe(false)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: null,
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
    expect(wrapper.vm.selectedResource).toEqual(null)
  })

  test('when creating it doesnt fetch resources on mount if the field is searchable', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: '',
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'posts',
        viaResource: '',
        viaResourceId: '',
      },
    })

    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.selectedResourceId).toEqual(null)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(false)
    expect(wrapper.vm.initializingWithExistingResource).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: null,
        first: false,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([])
    expect(wrapper.vm.selectedResource).toEqual(null)
  })

  test('when creating via a related resource it selects the related resource on mount if the field is searchable', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Post',
          belongsToId: '',
          attribute: 'post',
          searchable: true,
          resourceName: 'posts',
        },
        resourceName: 'comments',
        viaResource: 'posts',
        viaResourceId: 1,
      },
    })

    expect(wrapper.vm.editingExistingResource).toBe(false)
    expect(wrapper.vm.selectedResourceId).toEqual(1)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: { current: 1, first: true, search: '', withTrashed: false },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([{ value: 1 }])
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
  })

  test('if editing an existing resource it selects the related resource on mount if the field is not searchable', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: 1,
          attribute: 'user',
          searchable: false,
          resourceName: 'users',
        },
        resourceName: 'posts',
        viaResource: '',
        viaResourceId: '',
      },
    })

    expect(wrapper.vm.editingExistingResource).toBe(true)
    expect(wrapper.vm.selectedResourceId).toEqual(1)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.initializingWithExistingResource).toBe(false)
    expect(wrapper.vm.isSearchable).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
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
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })
  })

  test('if editing an existing resource it selects the related resource on mount if the field is searchable', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: 1,
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'posts',
      },
    })

    expect(wrapper.vm.editingExistingResource).toBe(true)
    expect(wrapper.vm.selectedResourceId).toEqual(1)
    expect(wrapper.vm.shouldSelectInitialResource).toBe(true)
    expect(wrapper.vm.initializingWithExistingResource).toBe(true)
    expect(wrapper.vm.isSearchable).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: { current: 1, first: true, search: '', withTrashed: false },
    })

    await flushPromises()

    expect(wrapper.vm.availableResources).toEqual([{ value: 1 }])
    expect(wrapper.vm.selectedResourceId).toEqual(1)
    expect(wrapper.vm.selectedResource).toEqual({ value: 1 })

    // Ensure it turns off selection of the initial resource after fetching the first time
    expect(wrapper.vm.initializingWithExistingResource).toBe(false)
  })

  test('it determines if its related resource soft deletes', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: 1,
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'videos',
      },
    })

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(true)
  })

  test('including trashed resources in the available resources can be enabled when a resource supports soft-deleting', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: '',
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'videos',
      },
    })

    wrapper.vm.enableWithTrashed()

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(true)
    expect(wrapper.vm.withTrashed).toBe(true)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: null,
        first: false,
        search: '',
        withTrashed: true,
      },
    })
  })

  test('including trashed resources in the available resources cannot be enabled when a resource doesnt support soft-deleting', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Author',
          belongsToId: '',
          attribute: 'author',
          searchable: false,
          resourceName: 'authors', // This resource doesnt support soft-deleting
        },
        resourceName: 'videos',
      },
    })

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(false)
    expect(wrapper.vm.withTrashed).toBe(false)
    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: null,
        first: false,
        search: '',
        withTrashed: false,
      },
    })
  })

  test('including trashed resources in the available resources is disabled by default', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: '',
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'videos',
      },
    })

    // wrapper.vm.enableWithTrashed()
    expect(wrapper.vm.softDeletes).toBe(false)
    expect(wrapper.vm.withTrashed).toBe(false)

    expect(wrapper.vm.queryParams).toEqual({
      params: {
        current: null,
        first: false,
        search: '',
        withTrashed: false,
      },
    })

    await flushPromises()
  })

  test('it determines if its related resource doesnt soft delete', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'Author',
          belongsToId: 1,
          attribute: 'author',
          searchable: true,
          resourceName: 'authors',
        },
        resourceName: 'videos',
      },
    })

    await flushPromises()

    expect(wrapper.vm.softDeletes).toBe(false)
  })

  test('it correctly handles filling the formData object for submit', async () => {
    const wrapper = shallowMount(BelongsToField, {
      stubs: ['default-field'],
      propsData: {
        field: {
          name: 'User',
          belongsToId: 1,
          attribute: 'user',
          searchable: true,
          resourceName: 'users',
        },
        resourceName: 'videos',
      },
    })

    await flushPromises()

    const expectedFormData = new FormData()
    expectedFormData.append('user', 1)
    expectedFormData.append('user_trashed', false)

    const formData = new FormData()
    wrapper.vm.field.fill(formData)

    expect(formData).toEqual(expectedFormData)
  })
})
