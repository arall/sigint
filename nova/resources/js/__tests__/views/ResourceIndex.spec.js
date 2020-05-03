import { shallowMount } from '@vue/test-utils'
import { createRenderer } from 'vue-server-renderer'
import Index from '@/views/Index.vue'

// Create a renderer for snapshot testing
const renderer = createRenderer()

// Nova global mock
// class Nova {
//     constructor(config) {}

//     request() {
//         return {
//             get() {
//                 return { data: {} }
//             },
//         }
//     }
// }

// global.Nova = new Nova()

describe('Index.vue', () => {
  it('renders', () => {
    const wrapper = shallowMount(Index, {
      stubs: ['loading-view', 'cards'],
      propsData: {
        resourceName: 'posts',
      },
    })
    renderer.renderToString(wrapper.vm, (err, str) => {
      if (err) throw new Error(err)
      expect(str).toMatchSnapshot()
    })
  })

  it('renders after loading', () => {
    const wrapper = shallowMount(Index, {
      stubs: ['loading-view', 'cards'],
      propsData: {
        resourceName: 'posts',
      },
    })

    expect(wrapper.vm.initialLoading).toEqual(false)
  })

  it('should show its cards', () => {
    const $route = { params: { resourceName: 'posts' } }
    const wrapper = shallowMount(Index, {
      stubs: ['loading-view', 'cards'],
      mocks: {
        $route,
      },
      propsData: {
        resourceName: 'posts',
      },
    })

    // wrapper.setData({
    //     cards: [{}],
    // })

    expect(wrapper.vm.shouldShowCards).toEqual(true)
  })
})
