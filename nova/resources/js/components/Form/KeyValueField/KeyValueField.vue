<template>
  <default-field :field="field" :errors="errors" :full-width-content="true">
    <template slot="field">
      <KeyValueTable
        :edit-mode="!field.readonly"
        :can-delete-row="field.canDeleteRow"
      >
        <KeyValueHeader
          :key-label="field.keyLabel"
          :value-label="field.valueLabel"
        />

        <div class="bg-white overflow-hidden key-value-items">
          <KeyValueItem
            v-for="(item, index) in theData"
            :index="index"
            @remove-row="removeRow"
            :item.sync="item"
            :key="item.id"
            :ref="item.id"
            :read-only="field.readonly"
            :read-only-keys="field.readonlyKeys"
            :can-delete-row="field.canDeleteRow"
          />
        </div>
      </KeyValueTable>

      <div
        class="mr-11"
        v-if="!field.readonly && !field.readonlyKeys && field.canAddRow"
      >
        <button
          @click="addRowAndSelect"
          type="button"
          class="btn btn-link dim cursor-pointer rounded-lg mx-auto text-primary mt-3 px-3 rounded-b-lg flex items-center"
        >
          <icon type="add" width="24" height="24" view-box="0 0 24 24" />
          <span class="ml-1">{{ field.actionText }}</span>
        </button>
      </div>
    </template>
  </default-field>
</template>

<script>
import { FormField, HandlesValidationErrors } from 'laravel-nova'
import KeyValueItem from '@/components/Form/KeyValueField/KeyValueItem'
import KeyValueHeader from '@/components/Form/KeyValueField/KeyValueHeader'
import KeyValueTable from '@/components/Form/KeyValueField/KeyValueTable'

function guid() {
  var S4 = function () {
    return (((1 + Math.random()) * 0x10000) | 0).toString(16).substring(1)
  }
  return (
    S4() +
    S4() +
    '-' +
    S4() +
    '-' +
    S4() +
    '-' +
    S4() +
    '-' +
    S4() +
    S4() +
    S4()
  )
}

export default {
  mixins: [HandlesValidationErrors, FormField],

  components: { KeyValueTable, KeyValueHeader, KeyValueItem },

  data: () => ({ theData: [] }),

  mounted() {
    this.theData = _.map(this.value || {}, (value, key) => ({
      id: guid(),
      key,
      value,
    }))

    if (this.theData.length == 0) {
      this.addRow()
    }
  },

  methods: {
    /**
     * Provide a function that fills a passed FormData object with the
     * field's internal value attribute.
     */
    fill(formData) {
      formData.append(this.field.attribute, JSON.stringify(this.finalPayload))
    },

    /**
     * Add a row to the table.
     */
    addRow() {
      return _.tap(guid(), id => {
        this.theData = [...this.theData, { id, key: '', value: '' }]
        return id
      })
    },

    /**
     * Add a row to the table and select its first field.
     */
    addRowAndSelect() {
      return this.selectRow(this.addRow())
    },

    /**
     * Remove the row from the table.
     */
    removeRow(id) {
      return _.tap(
        _.findIndex(this.theData, row => row.id == id),
        index => this.theData.splice(index, 1)
      )
    },

    /**
     * Select the first field in a row with the given ref ID.
     */
    selectRow(refId) {
      return this.$nextTick(() => {
        this.$refs[refId][0].$refs.keyField.select()
      })
    },
  },

  computed: {
    /**
     * Return the final filtered json object
     */
    finalPayload() {
      return _(this.theData)
        .map(row => (row && row.key ? [row.key, row.value] : undefined))
        .reject(row => row === undefined)
        .fromPairs()
        .value()
    },
  },
}
</script>
