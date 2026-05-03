<template>
  <div class="space-y-4">
    <div
      v-if="toast.visible"
      class="fixed right-4 top-4 z-50 rounded-xl border px-4 py-3 text-sm shadow-2xl backdrop-blur"
      :class="toast.type === 'error'
        ? 'border-rose-500/30 bg-rose-950/90 text-rose-100'
        : 'border-emerald-500/30 bg-emerald-950/90 text-emerald-100'"
    >
      {{ toast.message }}
    </div>

    <div class="glass-card overflow-hidden">
      <div class="border-b border-white/10 px-4 py-4 sm:px-5">
        <div class="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div class="flex-1">
            <div class="section-heading text-lg">账号列表</div>
            <div class="section-subtitle mt-1">
              支持搜索、分页和批量复制。点击行可交给父组件打开详情抽屉。
            </div>
          </div>
          <div class="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-end">
            <input
              v-model="searchInput"
              type="text"
              placeholder="@email 或备注关键字"
              class="input-dark min-w-[220px] lg:w-[260px]"
            />
            <select v-model="sort" class="input-dark lg:w-[170px]">
              <option value="updated_at_desc">更新时间 ↓</option>
              <option value="updated_at_asc">更新时间 ↑</option>
              <option value="created_at_desc">创建时间 ↓</option>
              <option value="email_asc">邮箱 A-Z</option>
              <option value="email_desc">邮箱 Z-A</option>
            </select>
            <select v-model.number="pageSize" class="input-dark lg:w-[120px]">
              <option :value="20">20 / 页</option>
              <option :value="50">50 / 页</option>
              <option :value="100">100 / 页</option>
            </select>
            <button
              type="button"
              class="btn-secondary"
              :disabled="loading || selectedAccounts.length === 0"
              @click.stop="copySelectedEmails"
            >
              复制选中邮箱
            </button>
          </div>
        </div>
      </div>

      <div v-if="error" class="border-b border-white/10 px-4 py-3 text-sm text-rose-200 sm:px-5">
        <div class="rounded-xl border border-rose-500/30 bg-rose-950/50 px-4 py-3">
          {{ error }}
        </div>
      </div>

      <div v-if="loading" class="space-y-3 px-4 py-4 sm:px-5">
        <div class="h-12 animate-pulse rounded-2xl bg-white/5"></div>
        <div class="h-12 animate-pulse rounded-2xl bg-white/5"></div>
        <div class="h-12 animate-pulse rounded-2xl bg-white/5"></div>
      </div>

      <div v-else-if="rows.length === 0" class="px-4 py-12 text-center sm:px-5">
        <div class="text-base font-medium text-white">没有匹配的账号</div>
        <div class="mt-2 text-sm text-slate-400">
          可以换个分类、清空搜索词，或者等父组件触发刷新。
        </div>
      </div>

      <div v-else class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="border-b border-white/10 text-left text-slate-400">
              <th class="w-12 px-4 py-3 font-medium sm:px-5">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-white/20 bg-slate-900/80 text-blue-500"
                  :checked="allVisibleSelected"
                  :indeterminate.prop="someVisibleSelected && !allVisibleSelected"
                  @click.stop
                  @change="toggleSelectVisible($event)"
                />
              </th>
              <th class="px-4 py-3 font-medium sm:px-5">邮箱</th>
              <th class="px-4 py-3 font-medium">状态</th>
              <th class="px-4 py-3 font-medium">备注</th>
              <th class="px-4 py-3 font-medium">远端同步</th>
              <th class="px-4 py-3 font-medium">Allocation</th>
              <th class="px-4 py-3 text-right font-medium sm:px-5">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="account in rows"
              :key="account.email"
              class="cursor-pointer border-b border-white/5 transition hover:bg-white/5"
              @click="selectAccount(account)"
            >
              <td class="px-4 py-3 sm:px-5" @click.stop>
                <input
                  :checked="isSelected(account.email)"
                  type="checkbox"
                  class="h-4 w-4 rounded border-white/20 bg-slate-900/80 text-blue-500"
                  @click.stop
                  @change="toggleSelectAccount(account, $event)"
                />
              </td>
              <td class="px-4 py-3 align-top sm:px-5">
                <div class="font-mono text-xs text-slate-100">{{ account.email || '-' }}</div>
                <div class="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
                  <span>分类: {{ account.category || deriveFallbackCategory(account) }}</span>
                  <span v-if="account.updated_at">更新: {{ formatTimestamp(account.updated_at) }}</span>
                </div>
              </td>
              <td class="px-4 py-3 align-top">
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="badge in statusBadges(account)"
                    :key="badge.key"
                    class="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium"
                    :class="badge.className"
                  >
                    <span class="h-2 w-2 rounded-full" :class="badge.dotClass"></span>
                    {{ badge.label }}
                  </span>
                </div>
              </td>
              <td class="max-w-[260px] px-4 py-3 align-top text-sm text-slate-300">
                <div class="line-clamp-2 whitespace-pre-wrap break-words">
                  {{ account.notes || '—' }}
                </div>
              </td>
              <td class="px-4 py-3 align-top">
                <div class="flex flex-col gap-2">
                  <div class="flex flex-wrap gap-2">
                    <span
                      class="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium"
                      :class="remoteBadgeClass(account.remote?.cpa?.status)"
                    >
                      CPA {{ remoteLabel(account.remote?.cpa?.status) }}
                    </span>
                    <span
                      class="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium"
                      :class="remoteBadgeClass(account.remote?.sub2api?.status)"
                    >
                      Sub2API {{ remoteLabel(account.remote?.sub2api?.status) }}
                    </span>
                  </div>
                  <div class="text-[11px] text-slate-500">
                    {{ remoteDetail(account) }}
                  </div>
                </div>
              </td>
              <td class="px-4 py-3 align-top text-sm text-slate-300">
                <div v-if="hasAllocation(account)" class="space-y-1">
                  <div class="font-medium text-slate-100">{{ allocationTitle(account) }}</div>
                  <div class="text-xs text-slate-500">{{ allocationDetail(account) }}</div>
                </div>
                <span v-else class="text-slate-500">—</span>
              </td>
              <td class="px-4 py-3 text-right align-top sm:px-5">
                <div class="flex flex-wrap justify-end gap-2" @click.stop>
                  <button
                    type="button"
                    class="btn-secondary px-3 py-1.5 text-xs"
                    @click.stop="copySingleEmail(account)"
                  >
                    复制邮箱
                  </button>
                  <button
                    type="button"
                    class="btn-secondary px-3 py-1.5 text-xs"
                    @click.stop="copySinglePassword(account)"
                  >
                    复制密码
                  </button>
                  <button
                    type="button"
                    class="btn-secondary px-3 py-1.5 text-xs"
                    @click.stop="selectAccount(account)"
                  >
                    查看详情
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="border-t border-white/10 px-4 py-4 sm:px-5">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div class="text-sm text-slate-400">
            第 {{ page }}/{{ totalPages }} 页
            <span class="mx-1">·</span>
            共 {{ total }} 条
            <span v-if="selectedAccounts.length" class="mx-1">·</span>
            <span v-if="selectedAccounts.length">已选 {{ selectedAccounts.length }} 条</span>
          </div>
          <div class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="btn-secondary px-3 py-2 text-sm"
                :disabled="loading || page <= 1"
                @click="goToPreviousPage"
              >
                上一页
              </button>
              <button
                type="button"
                class="btn-secondary px-3 py-2 text-sm"
                :disabled="loading || !hasNextPage"
                @click="goToNextPage"
              >
                下一页
              </button>
            </div>
            <div class="flex items-center gap-2 text-sm text-slate-400">
              <span>跳到</span>
              <input
                v-model="pageInput"
                type="number"
                min="1"
                :max="String(totalPages)"
                class="input-dark w-24"
                @keyup.enter="applyPageInput"
              />
              <button
                type="button"
                class="btn-secondary px-3 py-2 text-sm"
                :disabled="loading"
                @click="applyPageInput"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'

const VALID_CATEGORIES = new Set([
  'registered',
  'inventory',
  'in_use',
  'invalid',
  'sold',
  'not_registered',
  'all',
])

const props = defineProps({
  category: {
    type: String,
    default: 'all',
    validator: (value) => VALID_CATEGORIES.has(value),
  },
  refreshKey: {
    type: Number,
    default: 0,
  },
})

const emit = defineEmits(['select-account', 'refresh-needed'])

const loading = ref(false)
const error = ref('')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const sort = ref('updated_at_desc')
const query = ref('')
const searchInput = ref('')
const pageInput = ref('1')
const selectedEmails = ref([])
const toast = ref({
  visible: false,
  message: '',
  type: 'success',
})

let searchTimer = null
let toastTimer = null
let requestToken = 0

const selectedAccounts = computed(() => rows.value.filter((account) => selectedEmails.value.includes(account.email)))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const hasNextPage = computed(() => page.value < totalPages.value)
const allVisibleSelected = computed(() => rows.value.length > 0 && rows.value.every((account) => isSelected(account.email)))
const someVisibleSelected = computed(() => rows.value.some((account) => isSelected(account.email)))

function normalizeCategory(value) {
  return VALID_CATEGORIES.has(value) ? value : 'all'
}

function resetSelection() {
  selectedEmails.value = []
}

function showToast(message, type = 'success') {
  toast.value = {
    visible: true,
    message,
    type,
  }
  if (toastTimer) {
    clearTimeout(toastTimer)
  }
  toastTimer = window.setTimeout(() => {
    toast.value.visible = false
  }, 2400)
}

async function fetchAccounts() {
  const currentToken = ++requestToken
  loading.value = true
  error.value = ''
  try {
    const result = await api.listAccounts({
      category: normalizeCategory(props.category),
      q: query.value || undefined,
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    })
    if (currentToken !== requestToken) {
      return
    }
    rows.value = Array.isArray(result?.items) ? result.items : []
    total.value = Number(result?.total || 0)
    page.value = Number(result?.page || 1)
    pageInput.value = String(page.value)
    selectedEmails.value = selectedEmails.value.filter((email) => rows.value.some((account) => account.email === email))
  } catch (err) {
    if (currentToken !== requestToken) {
      return
    }
    rows.value = []
    total.value = 0
    error.value = err?.message || '账号列表加载失败'
  } finally {
    if (currentToken === requestToken) {
      loading.value = false
    }
  }
}

function scheduleSearch(value) {
  searchInput.value = value
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = window.setTimeout(() => {
    query.value = searchInput.value.trim()
    page.value = 1
    pageInput.value = '1'
    fetchAccounts()
  }, 300)
}

watch(searchInput, (value) => {
  scheduleSearch(value)
})

watch(sort, () => {
  page.value = 1
  pageInput.value = '1'
  fetchAccounts()
})

watch(pageSize, () => {
  page.value = 1
  pageInput.value = '1'
  resetSelection()
  fetchAccounts()
})

watch(
  () => props.category,
  () => {
    page.value = 1
    pageInput.value = '1'
    query.value = ''
    searchInput.value = ''
    resetSelection()
    fetchAccounts()
  },
  { immediate: true },
)

watch(
  () => props.refreshKey,
  () => {
    resetSelection()
    fetchAccounts()
  },
)

function selectAccount(account) {
  emit('select-account', account)
}

function isSelected(email) {
  return selectedEmails.value.includes(email)
}

function toggleSelectAccount(account, event) {
  const checked = Boolean(event?.target?.checked)
  if (checked) {
    if (!isSelected(account.email)) {
      selectedEmails.value = [...selectedEmails.value, account.email]
    }
  } else {
    selectedEmails.value = selectedEmails.value.filter((email) => email !== account.email)
  }
}

function toggleSelectVisible(event) {
  const checked = Boolean(event?.target?.checked)
  if (checked) {
    const next = new Set(selectedEmails.value)
    rows.value.forEach((account) => {
      next.add(account.email)
    })
    selectedEmails.value = Array.from(next)
    return
  }
  const visibleEmails = new Set(rows.value.map((account) => account.email))
  selectedEmails.value = selectedEmails.value.filter((email) => !visibleEmails.has(email))
}

async function copyText(text) {
  if (!text) {
    throw new Error('没有可复制的内容')
  }
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'readonly')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  document.body.removeChild(textarea)
  if (!copied) {
    throw new Error('当前环境不支持剪贴板复制')
  }
}

async function copySingleEmail(account) {
  try {
    await copyText(account.email || '')
    showToast(`已复制 ${account.email}`)
  } catch (err) {
    showToast(err?.message || '复制邮箱失败', 'error')
  }
}

async function copySinglePassword(account) {
  if (!account?.password) {
    showToast('列表接口未返回密码，请在详情里复制', 'error')
    return
  }
  try {
    await copyText(account.password)
    showToast(`已复制 ${account.email} 的密码`)
  } catch (err) {
    showToast(err?.message || '复制密码失败', 'error')
  }
}

async function copySelectedEmails() {
  if (selectedAccounts.value.length === 0) {
    showToast('请先选择账号', 'error')
    return
  }
  const content = selectedAccounts.value
    .map((account) => account.email)
    .filter(Boolean)
    .join('\n')
  try {
    await copyText(content)
    showToast(`已复制 ${selectedAccounts.value.length} 个邮箱`)
  } catch (err) {
    showToast(err?.message || '批量复制失败', 'error')
  }
}

function goToPreviousPage() {
  if (page.value <= 1) {
    return
  }
  page.value -= 1
  pageInput.value = String(page.value)
  resetSelection()
  fetchAccounts()
}

function goToNextPage() {
  if (!hasNextPage.value) {
    return
  }
  page.value += 1
  pageInput.value = String(page.value)
  resetSelection()
  fetchAccounts()
}

function applyPageInput() {
  const parsed = Number.parseInt(String(pageInput.value || '').trim(), 10)
  const target = Number.isFinite(parsed) ? Math.min(Math.max(parsed, 1), totalPages.value) : page.value
  pageInput.value = String(target)
  if (target === page.value) {
    return
  }
  page.value = target
  resetSelection()
  fetchAccounts()
}

function formatTimestamp(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return '—'
  }
  const date = new Date(numeric * 1000)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hours}:${minutes}`
}

function deriveFallbackCategory(account) {
  if (account?.usage_status === 'sold') return 'sold'
  if (['invalid', 'deactivated', 'risk_blocked'].includes(account?.health_status)) return 'invalid'
  if (account?.registration_status !== 'registered') return 'not_registered'
  if (account?.usage_status === 'in_use') return 'in_use'
  if (account?.usage_status === 'inventory') return 'inventory'
  return 'registered'
}

function statusBadges(account) {
  const badges = []
  const usageStatus = account?.usage_status || ''
  const healthStatus = account?.health_status || ''
  const category = account?.category || deriveFallbackCategory(account)

  if (usageStatus === 'sold') {
    badges.push({
      key: 'usage-sold',
      label: '已售',
      className: 'border-fuchsia-500/30 bg-fuchsia-500/15 text-fuchsia-200',
      dotClass: 'bg-fuchsia-300',
    })
  } else if (healthStatus === 'deactivated') {
    badges.push({
      key: 'health-deactivated',
      label: '已停用',
      className: 'border-slate-500/30 bg-slate-500/15 text-slate-200',
      dotClass: 'bg-slate-300',
    })
  } else if (healthStatus === 'invalid') {
    badges.push({
      key: 'health-invalid',
      label: '失效',
      className: 'border-rose-500/30 bg-rose-500/15 text-rose-200',
      dotClass: 'bg-rose-300',
    })
  } else if (healthStatus === 'quota_exhausted') {
    badges.push({
      key: 'health-quota',
      label: '额度耗尽',
      className: 'border-amber-500/30 bg-amber-500/15 text-amber-200',
      dotClass: 'bg-amber-300',
    })
  } else if (healthStatus === 'valid' && (usageStatus === 'inventory' || category === 'inventory')) {
    badges.push({
      key: 'usage-inventory',
      label: '库存',
      className: 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200',
      dotClass: 'bg-emerald-300',
    })
  } else if (healthStatus === 'valid' && (usageStatus === 'in_use' || category === 'in_use')) {
    badges.push({
      key: 'usage-in-use',
      label: '使用中',
      className: 'border-sky-500/30 bg-sky-500/15 text-sky-200',
      dotClass: 'bg-sky-300',
    })
  } else if (category === 'not_registered') {
    badges.push({
      key: 'registration-pending',
      label: '未注册',
      className: 'border-slate-500/30 bg-slate-500/15 text-slate-200',
      dotClass: 'bg-slate-300',
    })
  } else {
    badges.push({
      key: 'registered',
      label: '已注册',
      className: 'border-violet-500/30 bg-violet-500/15 text-violet-200',
      dotClass: 'bg-violet-300',
    })
  }

  if (account?.is_main_account === true) {
    badges.push({
      key: 'main-account',
      label: '主号',
      className: 'border-orange-500/30 bg-orange-500/15 text-orange-100',
      dotClass: 'bg-orange-300',
    })
  }

  return badges
}

function remoteBadgeClass(status) {
  switch (status) {
    case 'present':
      return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200'
    case 'failed':
      return 'border-rose-500/30 bg-rose-500/15 text-rose-200'
    case 'missing':
      return 'border-amber-500/30 bg-amber-500/15 text-amber-200'
    case 'disabled':
      return 'border-slate-500/30 bg-slate-500/15 text-slate-200'
    default:
      return 'border-white/10 bg-white/5 text-slate-300'
  }
}

function remoteLabel(status) {
  switch (status) {
    case 'present':
      return '已同步'
    case 'failed':
      return '失败'
    case 'missing':
      return '缺少'
    case 'disabled':
      return '已禁用'
    default:
      return '未知'
  }
}

function remoteDetail(account) {
  const details = []
  const cpa = account?.remote?.cpa
  const sub2api = account?.remote?.sub2api
  if (cpa?.auth_name) {
    details.push(`CPA:${cpa.auth_name}`)
  }
  if (sub2api?.group) {
    details.push(`组:${sub2api.group}`)
  }
  if (cpa?.error) {
    details.push(`CPA错误:${cpa.error}`)
  }
  if (sub2api?.error) {
    details.push(`Sub2API错误:${sub2api.error}`)
  }
  return details.join(' · ') || '无额外远端信息'
}

function hasAllocation(account) {
  const allocation = account?.allocation
  return Boolean(
    allocation
    && (allocation.status || allocation.project || allocation.allocated_to || allocation.allocation_id),
  )
}

function allocationTitle(account) {
  const allocation = account?.allocation || {}
  return allocation.project || allocation.allocated_to || allocation.status || '已记录'
}

function allocationDetail(account) {
  const allocation = account?.allocation || {}
  const parts = []
  if (allocation.status) parts.push(`状态:${allocation.status}`)
  if (allocation.allocated_to) parts.push(`对象:${allocation.allocated_to}`)
  if (allocation.allocation_id) parts.push(`ID:${allocation.allocation_id}`)
  if (allocation.release_reason) parts.push(`释放:${allocation.release_reason}`)
  return parts.join(' · ') || '—'
}

onBeforeUnmount(() => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  if (toastTimer) {
    clearTimeout(toastTimer)
  }
})

defineExpose({
  refresh: fetchAccounts,
  clearSelection: resetSelection,
})
</script>
