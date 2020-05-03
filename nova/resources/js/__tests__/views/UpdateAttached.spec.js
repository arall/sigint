import { mount, shallowMount, createLocalVue } from '@vue/test-utils'
import UpdateAttached from '@/views/UpdateAttached'
// import flushPromises from 'flush-promises'

describe('UpdateAttached', () => {
  test('it loads all the available resources if its not searchable', () => {
    window.Nova = {}
    window.Nova.config = {
      resources: [
        {
          uriKey: 'users',
          label: 'Users',
          singularLabel: 'User',
          authorizedToCreate: true,
          searchable: false,
        },
        {
          uriKey: 'roles',
          label: 'Roles',
          singularLabel: 'Role',
          authorizedToCreate: true,
          searchable: false,
        },
      ],
    }

    const wrapper = mount(UpdateAttached, {
      propsData: {
        resourceName: 'users',
        resourceId: 100,
        relatedResourceName: 'roles',
        relatedResourceId: 25,
        // viaResource: {},
        // viaResourceId: {},
        // viaRelationship: {},
        // polymorphic: false,
      },
    })

    wrapper.setData({
      field: {},
    })

    // expect(wrapper).toMatchSnapshot()
  })
})
