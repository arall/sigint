Nova.booting((Vue, router, store) => {
  router.addRoutes([
    {
      name: '{{ component }}',
      path: '/{{ component }}',
      component: require('./components/Tool'),
    },
  ])
})
