import { mount, shallowMount, createLocalVue } from '@vue/test-utils'
import PortalVue from 'portal-vue'
import ActionSelector from '@/components/ActionSelector'
import flushPromises from 'flush-promises'

const localVue = createLocalVue()
localVue.use(PortalVue)

describe('ActionSelector', () => {
  test('it renders correctly with actions and pivot action', () => {
    const wrapper = mount(ActionSelector, {
      localVue,
      propsData: {
        selectedResources: [1, 2, 3],
        resourceName: 'posts',
        actions: [
          { uriKey: 'action-1', name: 'Action 1' },
          { uriKey: 'action-2', name: 'Action 2' },
        ],
        pivotActions: [
          { uriKey: 'action-3', name: 'Action 3' },
          { uriKey: 'action-4', name: 'Action 4' },
        ],
        pivotName: 'Pivot',
      },
    })

    expect(wrapper).toMatchSnapshot()
  })
})
