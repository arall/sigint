<template>
  <div>
    <!-- Available Lenses -->
    <div v-for="lens in lenses" class="px-3">
      <router-link
        :to="{
          name: 'lens',
          params: { resourceName: resourceName, lens: lens.uriKey },
        }"
        class="dim block text-base text-90 no-underline leading-normal my-2"
      >
        {{ lens.name }}
      </router-link>
    </div>
  </div>
</template>

<script>
export default {
  props: ['resourceName', 'lenses'],
}
</script>
