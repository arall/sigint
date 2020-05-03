<template>
  <div>
    <!-- <h4 class="text-90 font-normal text-2xl mb-3">{{ panel.name }}</h4> -->

    <div :key="field + resourceId" v-for="field in panel.fields">
      <component
        :is="'detail-' + field.component"
        :resource-name="resourceName"
        :resource-id="resourceId"
        :resource="resource"
        :field="field"
        @actionExecuted="actionExecuted"
      />
    </div>
  </div>
</template>

<script>
import { BehavesAsPanel } from 'laravel-nova'

export default {
  mixins: [BehavesAsPanel],
}
</script>
