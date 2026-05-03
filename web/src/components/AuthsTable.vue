<template>
  <div class="space-y-4">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-6 gap-3">
        <div>
          <label class="block text-xs text-gray-500 mb-1">分类</label>
          <select v-model="filterCategory" @change="applyFilters"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">全部（不含归档）</option>
            <option value="active">活跃</option>
            <option value="sold">已售</option>
            <option value="tradable">可交易</option>
            <option value="unusable">不可用</option>
            <option value="archive">归档</option>
            <option value="all">全部含归档</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Plan</label>
          <select v-model="filterPlan" @change="applyFilters"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">全部</option>
            <option value="team">Team</option>
            <option value="plus">Plus</option>
            <option value="free">Free</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">OAuth 文件</label>
          <select v-model="filterOauth" @change="applyFilters"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">全部</option>
            <option value="true">有</option>
            <option value="false">无</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Session 文件</label>
          <select v-model="filterSession" @change="applyFilters"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">全部</option>
            <option value="true">有</option>
            <option value="false">无</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">排序</label>
          <select v-model="sort" @change="applyFilters"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="email_asc">邮箱 ↑</option>
            <option value="email_desc">邮箱 ↓</option>
            <option value="expired_asc">过期 ↑</option>
            <option value="expired_desc">过期 ↓</option>
            <option value="category_asc">分类 ↑</option>
            <option value="plan_asc">Plan ↑</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">搜索邮箱</label>
          <input v-model="searchQ" @keyup.enter="applyFilters" @blur="applyFilters" type="text"
            placeholder="包含的邮箱字符串..."
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500" />
        </div>
      </div>

      <div v-if="facets" class="mt-3 flex flex-wrap gap-2 text-xs">
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">活跃 <b class="text-green-400">{{ facets.category.active }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">已售 <b class="text-cyan-300">{{ facets.category.sold }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">可交易 <b class="text-emerald-400">{{ facets.category.tradable }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">不可用 <b class="text-red-400">{{ facets.category.unusable }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">归档 <b class="text-gray-400">{{ facets.category.archive }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">Team <b class="text-blue-300">{{ facets.plan_type.team }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">Plus <b class="text-purple-300">{{ facets.plan_type.plus }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">Free <b class="text-amber-300">{{ facets.plan_type.free }}</b></span>
        <span class="px-2 py-1 rounded bg-gray-800 text-gray-300">Unknown <b class="text-gray-300">{{ facets.plan_type.unknown }}</b></span>
      </div>
    </div>

    <div v-if="selectedCount" class="bg-gray-900 border border-blue-500/30 rounded-xl px-4 py-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div class="text-sm text-gray-300">
        已选择 <span class="text-white font-medium">{{ selectedCount }}</span> 个 Team 账号
      </div>
      <div class="flex flex-wrap gap-2">
        <button v-for="action in bulkActions" :key="action.value" type="button"
          class="px-3 py-1.5 rounded-lg text-xs font-medium border transition disabled:opacity-50 disabled:cursor-not-allowed"
          :class="action.class"
          :disabled="bulkLoading"
          @click="runBulkAction(action.value)">
          {{ bulkLoading ? '处理中...' : action.label }}
        </button>
        <button type="button" class="px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-700 text-gray-300 bg-gray-800 hover:bg-gray-700"
          :disabled="bulkLoading"
          @click="clearSelection">
          清空
        </button>
      </div>
    </div>

    <div v-if="bulkMessage" class="px-4 py-3 rounded-lg text-sm border" :class="bulkMessageClass">
      <div>{{ bulkMessage }}</div>
      <div v-if="bulkFailures.length" class="mt-2 space-y-1 text-xs">
        <div v-for="item in bulkFailures" :key="item.email + item.message" class="text-red-300">
          {{ item.email || '-' }}：{{ item.message || item.skipped_reason }}
        </div>
      </div>
    </div>

    <div v-if="error" class="px-4 py-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20">
      {{ error }}
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div class="text-sm text-gray-400">
          共 <span class="text-white font-medium">{{ total }}</span> 个账号
          <span v-if="loading" class="ml-2 text-blue-400">加载中...</span>
        </div>
        <div class="flex items-center gap-2">
          <label class="text-xs text-gray-500">每页</label>
          <select v-model.number="pageSize" @change="onPageSizeChange"
            class="px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-200">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="200">200</option>
          </select>
          <button @click="reload" :disabled="loading"
            class="px-3 py-1 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-300">
            刷新
          </button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-gray-400 text-left border-b border-gray-800">
              <th class="px-4 py-3 font-medium w-12">
                <input type="checkbox" :checked="allSelectableChecked" :disabled="!selectableRecords.length"
                  class="h-4 w-4 rounded border-gray-700 bg-gray-800"
                  @change="togglePageSelection" />
              </th>
              <th class="px-4 py-3 font-medium w-12">#</th>
              <th class="px-4 py-3 font-medium">邮箱</th>
              <th class="px-4 py-3 font-medium w-24">Plan</th>
              <th class="px-4 py-3 font-medium w-28">分类</th>
              <th class="px-4 py-3 font-medium w-24 text-center">OAuth</th>
              <th class="px-4 py-3 font-medium w-24 text-center">Session</th>
              <th class="px-4 py-3 font-medium w-24 text-center">已禁用</th>
              <th class="px-4 py-3 font-medium w-44">过期时间</th>
              <th class="px-4 py-3 font-medium w-32">凭证来源</th>
              <th class="px-4 py-3 font-medium w-20 text-center">文件数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in records" :key="r.email + ':' + r.team_hash"
              class="border-b border-gray-800/50 transition"
              :class="r.is_limited_view ? 'bg-gray-950/30 text-gray-500' : 'hover:bg-gray-800/30'">
              <td class="px-4 py-3" @click.stop>
                <input type="checkbox" :checked="isSelected(r.email)" :disabled="!isSelectable(r)"
                  class="h-4 w-4 rounded border-gray-700 bg-gray-800 disabled:opacity-30"
                  @change="toggleSelection(r)" />
              </td>
              <td class="px-4 py-3 text-gray-500">{{ pageStart + i + 1 }}</td>
              <td class="px-4 py-3 font-mono text-xs" :class="r.is_limited_view ? 'text-gray-500' : 'text-gray-200'">
                {{ r.email }}
              </td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs font-medium" :class="planClass(r.plan_type)">
                  {{ planLabel(r.plan_type) }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs font-medium" :class="categoryClass(r.category)">
                  {{ categoryLabel(r.category) }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span class="px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="r.has_oauth ? 'bg-blue-500/10 text-blue-400' : 'bg-gray-700/50 text-gray-500'">
                  {{ r.has_oauth ? '有' : '无' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span class="px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="r.has_session ? 'bg-purple-500/10 text-purple-400' : 'bg-gray-700/50 text-gray-500'">
                  {{ r.has_session ? '有' : '无' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span v-if="r.disabled === true" class="px-2 py-0.5 rounded-full text-xs bg-red-500/10 text-red-400">是</span>
                <span v-else-if="r.disabled === false" class="px-2 py-0.5 rounded-full text-xs bg-green-500/10 text-green-400">否</span>
                <span v-else class="text-xs text-gray-600">-</span>
              </td>
              <td class="px-4 py-3 text-xs text-gray-400">{{ formatDate(r.expired) }}</td>
              <td class="px-4 py-3 text-xs text-gray-400">{{ r.credential_source || '-' }}</td>
              <td class="px-4 py-3 text-center text-xs text-gray-400">{{ r.file_count }}</td>
            </tr>
            <tr v-if="!records.length && !loading">
              <td colspan="11" class="px-4 py-12 text-center text-gray-500 text-sm">
                没有符合条件的账号
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="totalPages > 1" class="px-4 py-3 border-t border-gray-800 flex items-center justify-between">
        <div class="text-xs text-gray-500">
          显示 {{ pageStart + 1 }} - {{ pageEnd }} / {{ total }}
        </div>
        <div class="flex items-center gap-2">
          <button @click="goToPage(1)" :disabled="page === 1 || loading"
            class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
            首页
          </button>
          <button @click="goToPage(page - 1)" :disabled="page === 1 || loading"
            class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
            上一页
          </button>
          <span class="text-xs text-gray-400 px-2">{{ page }} / {{ totalPages }}</span>
          <button @click="goToPage(page + 1)" :disabled="page >= totalPages || loading"
            class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
            下一页
          </button>
          <button @click="goToPage(totalPages)" :disabled="page >= totalPages || loading"
            class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
            末页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['bulk-complete'])

const filterCategory = ref('')
const filterPlan = ref('')
const filterOauth = ref('')
const filterSession = ref('')
const sort = ref('email_asc')
const searchQ = ref('')
const page = ref(1)
const pageSize = ref(20)

const records = ref([])
const total = ref(0)
const facets = ref(null)
const loading = ref(false)
const error = ref('')
const selectedEmails = ref(new Set())
const bulkLoading = ref(false)
const bulkMessage = ref('')
const bulkMessageClass = ref('')
const bulkFailures = ref([])

const bulkActions = [
  { value: 'mark-invalid', label: '标记失效', class: 'bg-amber-600/10 text-amber-300 border-amber-500/30 hover:bg-amber-600/20' },
  { value: 'sell', label: '卖出', class: 'bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20' },
  { value: 'delete', label: '删除', class: 'bg-red-600/10 text-red-300 border-red-500/30 hover:bg-red-600/20' },
]

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const pageStart = computed(() => (page.value - 1) * pageSize.value)
const pageEnd = computed(() => Math.min(total.value, pageStart.value + records.value.length))
const selectedCount = computed(() => selectedEmails.value.size)
const selectableRecords = computed(() => records.value.filter(isSelectable))
const allSelectableChecked = computed(() => (
  selectableRecords.value.length > 0 && selectableRecords.value.every((r) => selectedEmails.value.has(r.email))
))

watch(() => props.refreshKey, () => {
  reload()
})

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    }
    if (filterCategory.value) params.category = filterCategory.value
    if (filterPlan.value) params.plan_type = filterPlan.value
    if (filterOauth.value !== '') params.has_oauth = filterOauth.value === 'true'
    if (filterSession.value !== '') params.has_session = filterSession.value === 'true'
    if (searchQ.value.trim()) params.q = searchQ.value.trim()

    const resp = await api.getAuthsAccounts(params)
    records.value = resp.items || []
    total.value = resp.total || 0
    facets.value = {
      category: resp.facets?.category || {},
      plan_type: resp.facets?.plan_type || {},
    }
    selectedEmails.value = new Set([...selectedEmails.value].filter((email) => records.value.some((r) => r.email === email && isSelectable(r))))
  } catch (e) {
    error.value = e.message
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  clearSelection()
  reload()
}

function onPageSizeChange() {
  page.value = 1
  clearSelection()
  reload()
}

function goToPage(p) {
  if (p < 1 || p > totalPages.value || loading.value) return
  page.value = p
  clearSelection()
  reload()
}

function isSelectable(record) {
  return Boolean(record?.is_team_plan && !record?.is_limited_view)
}

function isSelected(email) {
  return selectedEmails.value.has(email)
}

function toggleSelection(record) {
  if (!isSelectable(record)) return
  const next = new Set(selectedEmails.value)
  if (next.has(record.email)) next.delete(record.email)
  else next.add(record.email)
  selectedEmails.value = next
}

function togglePageSelection() {
  const next = new Set(selectedEmails.value)
  if (allSelectableChecked.value) {
    selectableRecords.value.forEach((record) => next.delete(record.email))
  } else {
    selectableRecords.value.forEach((record) => next.add(record.email))
  }
  selectedEmails.value = next
}

function clearSelection() {
  selectedEmails.value = new Set()
}

function selectedItems() {
  return records.value
    .filter((record) => selectedEmails.value.has(record.email) && isSelectable(record))
    .map((record) => ({
      email: record.email,
      plan_type: record.plan_type,
      is_team_plan: record.is_team_plan,
    }))
}

function actionLabel(action) {
  return {
    'mark-invalid': '标记失效',
    sell: '卖出',
    delete: '删除',
  }[action] || action
}

function actionDescription(action) {
  if (action === 'sell') return '会先清理已启用 CPA / Sub2API 远端记录，再标记为已售。'
  if (action === 'delete') return '会删除本地管理账号及关联资源，且可能改变远端状态。'
  return '只改本地生命周期状态。'
}

function showBulkMessage(text, kind = 'success', failures = []) {
  bulkMessage.value = text
  bulkFailures.value = failures.slice(0, 5)
  bulkMessageClass.value = kind === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
}

async function runBulkAction(action) {
  const items = selectedItems()
  if (!items.length) return
  const label = actionLabel(action)
  if (!window.confirm(`确认${label} ${items.length} 个账号？${actionDescription(action)}`)) return

  bulkLoading.value = true
  error.value = ''
  try {
    const preview = await api.bulkAccountAction({ action, items, options: {}, confirm: false })
    const previewRows = preview.results || []
    const previewOk = previewRows.filter((item) => item.ok).length
    const previewSkipped = previewRows.filter((item) => item.status === 'skipped').length
    if (!window.confirm(`预览结果：可执行 ${previewOk}，跳过 ${previewSkipped}。确认继续执行？`)) return

    const result = await api.bulkAccountAction({ action, items, options: {}, confirm: true })
    const rows = result.results || []
    const success = rows.filter((item) => item.ok && item.status === 'done').length
    const skipped = rows.filter((item) => item.status === 'skipped').length
    const failed = rows.filter((item) => item.status === 'failed').length
    const failures = rows.filter((item) => item.status === 'failed' || item.status === 'skipped')
    showBulkMessage(`${label}完成：成功 ${success}，跳过 ${skipped}，失败 ${failed}`, failed ? 'error' : 'success', failures)
    clearSelection()
    emit('bulk-complete', result)
    await reload()
  } catch (e) {
    error.value = e.message
  } finally {
    bulkLoading.value = false
  }
}

function categoryLabel(c) {
  return {
    active: '活跃',
    sold: '已售',
    tradable: '可交易',
    unusable: '不可用',
    archive: '归档',
  }[c] || c || '未知'
}

function categoryClass(c) {
  return {
    active: 'bg-green-500/10 text-green-400',
    sold: 'bg-cyan-500/10 text-cyan-300',
    tradable: 'bg-emerald-500/10 text-emerald-400',
    unusable: 'bg-red-500/10 text-red-400',
    archive: 'bg-gray-500/10 text-gray-400',
  }[c] || 'bg-gray-500/10 text-gray-300'
}

function planLabel(value) {
  return {
    team: 'Team',
    plus: 'Plus',
    free: 'Free',
    unknown: 'Unknown',
  }[value] || value || 'Unknown'
}

function planClass(value) {
  return {
    team: 'bg-blue-500/10 text-blue-300',
    plus: 'bg-purple-500/10 text-purple-300',
    free: 'bg-amber-500/10 text-amber-300',
    unknown: 'bg-gray-500/10 text-gray-300',
  }[value] || 'bg-gray-500/10 text-gray-300'
}

function formatDate(value) {
  if (!value) return '-'
  let d
  if (typeof value === 'number') {
    d = new Date(value < 1e12 ? value * 1000 : value)
  } else if (typeof value === 'string') {
    if (/^\d+$/.test(value)) {
      const num = Number(value)
      d = new Date(num < 1e12 ? num * 1000 : num)
    } else {
      d = new Date(value)
    }
  } else {
    return '-'
  }
  if (Number.isNaN(d.getTime())) return String(value)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

onMounted(() => {
  reload()
})
</script>
