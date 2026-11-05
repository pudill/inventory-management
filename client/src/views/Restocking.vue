<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-row">
        <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
        <span class="budget-value">{{ formatMoney(budget) }}</span>
      </div>
      <input
        id="budget-slider"
        type="range"
        min="0"
        max="25000"
        step="250"
        v-model.number="budget"
        class="budget-slider"
      />
    </div>

    <div v-if="loading" class="loading">{{ t('restocking.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ rows.length }})</h3>
        </div>
        <div v-if="rows.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.include') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.supplier') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.item_sku">
                <td><input type="checkbox" v-model="row.selected" /></td>
                <td><strong>{{ row.item_sku }}</strong></td>
                <td>{{ row.item_name }}</td>
                <td>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    class="qty-input"
                    v-model.number="row.quantity"
                  />
                </td>
                <td>{{ formatMoney(row.unit_cost) }}</td>
                <td>{{ formatMoney(lineTotal(row)) }}</td>
                <td>{{ row.lead_time_days }}</td>
                <td>{{ row.supplier }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card summary-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.summary') }}</h3>
        </div>
        <div class="summary-grid">
          <div>
            <div class="summary-label">{{ t('restocking.selectedTotal') }}</div>
            <div :class="['summary-value', { over: overBudget }]">{{ formatMoney(selectedTotal) }}</div>
          </div>
          <div>
            <div class="summary-label">{{ t('restocking.budget') }}</div>
            <div class="summary-value">{{ formatMoney(budget) }}</div>
          </div>
          <div>
            <div class="summary-label">{{ t('restocking.remaining') }}</div>
            <div :class="['summary-value', { over: overBudget }]">{{ formatMoney(budget - selectedTotal) }}</div>
          </div>
        </div>
        <div v-if="overBudget" class="error">
          {{ t('restocking.overBudget', { amount: formatMoney(selectedTotal - budget) }) }}
        </div>
        <div v-if="successMessage" class="success-message">{{ successMessage }}</div>
        <div v-if="submitError" class="error">{{ submitError }}</div>
        <button class="place-order-btn" :disabled="!canSubmit" @click="placeOrder">
          {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
        </button>
      </div>
    </template>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

// NOTE: This page intentionally ignores the shared FilterBar (useFilters);
// recommendations depend only on the budget slider.
export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale } = useI18n()

    const currencySymbol = computed(() => (currentCurrency.value === 'JPY' ? '¥' : '$'))
    const budget = ref(5000)
    const rows = ref([])
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref('')
    const submitError = ref('')

    const formatMoney = (value) => {
      const n = Number(value) || 0
      return `${currencySymbol.value}${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    }

    const formatDate = (dateString) => {
      const d = new Date(dateString)
      if (isNaN(d.getTime())) return dateString
      return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    }

    // A quantity is valid only if it is a positive integer
    const validQty = (row) => Number.isInteger(row.quantity) && row.quantity >= 1
    const lineTotal = (row) => (validQty(row) ? row.quantity * row.unit_cost : 0)

    const selectedRows = computed(() => rows.value.filter(r => r.selected))
    const selectedTotal = computed(() => selectedRows.value.reduce((sum, r) => sum + lineTotal(r), 0))
    // Small epsilon guards against floating-point drift at exactly-equal totals
    const overBudget = computed(() => selectedTotal.value > budget.value + 0.005)
    const canSubmit = computed(() =>
      selectedRows.value.length > 0 &&
      selectedRows.value.every(validQty) &&
      !overBudget.value &&
      !submitting.value
    )

    // Monotonic request id so a slow, stale response cannot overwrite a newer one
    let requestId = 0
    const loadRecommendations = async () => {
      const id = ++requestId
      try {
        loading.value = rows.value.length === 0
        error.value = null
        const data = await api.getRestockRecommendations(budget.value)
        if (id !== requestId) return
        // Fresh recommendations replace any manual edits
        rows.value = data.items.map(item => ({
          ...item,
          quantity: item.recommended_quantity,
          selected: true
        }))
      } catch (err) {
        if (id !== requestId) return
        error.value = 'Failed to load recommendations: ' + err.message
      } finally {
        if (id === requestId) loading.value = false
      }
    }

    let debounceTimer = null
    watch(budget, () => {
      successMessage.value = ''
      submitError.value = ''
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendations, 300)
    })

    const placeOrder = async () => {
      if (!canSubmit.value) return
      submitting.value = true
      successMessage.value = ''
      submitError.value = ''
      try {
        const order = await api.createRestockOrder({
          budget: budget.value,
          items: selectedRows.value.map(r => ({ item_sku: r.item_sku, quantity: r.quantity }))
        })
        successMessage.value = t('restocking.success', {
          orderNumber: order.order_number,
          date: formatDate(order.expected_delivery)
        })
      } catch (err) {
        submitError.value = err.response?.data?.detail
          ? `${t('restocking.failed')}: ${typeof err.response.data.detail === 'string' ? err.response.data.detail : JSON.stringify(err.response.data.detail)}`
          : `${t('restocking.failed')}: ${err.message}`
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)
    onBeforeUnmount(() => clearTimeout(debounceTimer))

    return {
      t, budget, rows, loading, error, submitting, successMessage, submitError,
      formatMoney, lineTotal, selectedTotal, overBudget, canSubmit, placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-weight: 600;
  color: #0f172a;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
}

.qty-input {
  width: 90px;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  color: #0f172a;
}

.empty-state {
  padding: 1.5rem;
  color: #64748b;
  text-align: center;
}

.summary-card {
  margin-top: 1.5rem;
  padding-bottom: 1.25rem;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  padding: 0 1.25rem 1rem;
}

.summary-label {
  font-size: 0.813rem;
  color: #64748b;
}

.summary-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.summary-value.over {
  color: #dc2626;
}

.success-message {
  margin: 0 1.25rem 1rem;
  padding: 0.75rem 1rem;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
  color: #166534;
}

.summary-card .error {
  margin: 0 1.25rem 1rem;
}

.place-order-btn {
  margin: 0 1.25rem;
  padding: 0.625rem 1.25rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
