<template>
  <div
    class="fixed inset-0 z-50"
    :class="open ? 'pointer-events-auto' : 'pointer-events-none'"
    :aria-hidden="open ? 'false' : 'true'"
  >
    <div
      class="absolute inset-0 bg-slate-950/70 transition-opacity duration-500"
      :class="open ? 'opacity-100' : 'opacity-0'"
      @click="handleClose"
    />

    <aside
      class="absolute inset-y-0 right-0 flex w-full max-w-3xl transform justify-end transition-transform duration-500 ease-out"
      :class="open ? 'translate-x-0' : 'translate-x-full'"
    >
      <div class="flex h-full w-full flex-col border-l border-white/10 bg-slate-950/95 shadow-[0_0_80px_-30px_rgba(15,23,42,0.95)] backdrop-blur-xl">
        <div class="border-b border-white/10 px-5 py-4">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0 space-y-3">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="truncate text-lg font-semibold text-white">
                  {{ headerEmail }}
                </h2>
                <span class="inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium" :class="categoryBadgeClass">
                  {{ categoryLabel(category) }}
                </span>
                <span
                  v-if="isMain"
                  class="inline-flex items-center rounded-full border border-amber-400/20 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-200"
                >
                  主号
                </span>
              </div>
              <p class="text-sm text-slate-400">
                账号详情、认证文件、远端同步、库存状态和修复操作都集中在这里。
              </p>
            </div>
            <button
              type="button"
              class="btn-secondary h-10 w-10 shrink-0 px-0 text-lg"
              @click="handleClose"
            >
              ×
            </button>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto px-5 py-4">
          <div v-if="!email" class="glass-card-soft p-5 text-sm text-slate-400">
            未选择账号。
          </div>

          <div v-else class="space-y-4">
            <div
              v-if="noticeText"
              class="rounded-2xl border px-4 py-3 text-sm"
              :class="noticeClass"
            >
              {{ noticeText }}
            </div>

            <div v-if="loading" class="space-y-4">
              <div
                v-for="item in 4"
                :key="item"
                class="glass-card-soft h-24 animate-pulse"
              />
            </div>

            <template v-else>
              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  基本信息
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <dl v-else class="grid gap-3 md:grid-cols-2">
                    <div class="drawer-field">
                      <dt>邮箱</dt>
                      <dd class="font-mono text-xs text-slate-200">{{ account?.email || headerEmail }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>分类</dt>
                      <dd>
                        <span class="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium" :class="categoryBadgeClass">
                          {{ categoryLabel(category) }}
                        </span>
                      </dd>
                    </div>
                    <div class="drawer-field">
                      <dt>主号</dt>
                      <dd>{{ boolLabel(isMain) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>注册时间</dt>
                      <dd>{{ formatDateTime(account?.registered_at || account?.created_at) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>注册状态</dt>
                      <dd>{{ statusLabel(registrationStatus) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>Team 状态</dt>
                      <dd>{{ statusLabel(teamStatus) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>用途状态</dt>
                      <dd>{{ statusLabel(usageStatus) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>健康状态</dt>
                      <dd class="space-y-1">
                        <div>{{ statusLabel(healthStatus) }}</div>
                        <div v-if="health?.invalid_reason" class="text-xs text-amber-300">
                          原因：{{ invalidReasonLabel(health.invalid_reason) }}
                        </div>
                      </dd>
                    </div>
                    <div class="drawer-field">
                      <dt>停止同步</dt>
                      <dd>{{ boolLabel(!!account?.sync_disabled) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>Quota 用尽</dt>
                      <dd>{{ boolLabel(!!health?.is_quota_exhausted) }}</dd>
                    </div>
                  </dl>
                </div>
              </details>

              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  认证文件
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <div v-else class="space-y-3">
                    <div
                      v-for="item in credentialRows"
                      :key="item.key"
                      class="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3"
                    >
                      <div class="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                        <div class="min-w-0">
                          <div class="text-sm font-medium text-white">{{ item.label }}</div>
                          <div class="mt-1 break-all font-mono text-xs text-slate-400">
                            {{ item.path || '—' }}
                          </div>
                        </div>
                        <div class="flex flex-wrap gap-2">
                          <span class="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium" :class="item.exists ? 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200' : 'border-slate-500/20 bg-slate-500/10 text-slate-300'">
                            {{ item.exists ? '存在' : '缺失' }}
                          </span>
                          <span class="inline-flex items-center rounded-full border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-xs font-medium text-sky-200">
                            {{ item.type || 'unknown' }}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </details>

              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  远端同步
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <div v-else class="grid gap-3 md:grid-cols-2">
                    <div
                      v-for="item in remoteRows"
                      :key="item.key"
                      class="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3"
                    >
                      <div class="flex items-center justify-between gap-3">
                        <div class="text-sm font-medium text-white">{{ item.label }}</div>
                        <span class="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium" :class="remoteStatusClass(item.status)">
                          {{ remoteStatusLabel(item.status) }}
                        </span>
                      </div>
                      <dl class="mt-3 space-y-2 text-sm text-slate-300">
                        <div class="flex items-start justify-between gap-3">
                          <dt class="text-slate-500">最后检查</dt>
                          <dd class="text-right">{{ formatDateTime(item.block?.checked_at) }}</dd>
                        </div>
                        <div class="flex items-start justify-between gap-3">
                          <dt class="text-slate-500">文件名</dt>
                          <dd class="break-all text-right font-mono text-xs">
                            {{ item.block?.auth_name || '—' }}
                          </dd>
                        </div>
                        <div class="flex items-start justify-between gap-3">
                          <dt class="text-slate-500">分组</dt>
                          <dd class="break-all text-right">{{ item.block?.group || '—' }}</dd>
                        </div>
                        <div class="flex items-start justify-between gap-3">
                          <dt class="text-slate-500">错误</dt>
                          <dd class="break-all text-right text-rose-200">
                            {{ item.block?.error || '—' }}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </div>
                </div>
              </details>

              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  分配信息
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <div v-else-if="isMain" class="text-sm text-slate-400">
                    主号无分配信息。
                  </div>
                  <div v-else-if="hasAllocation" class="grid gap-3 md:grid-cols-2">
                    <div class="drawer-field">
                      <dt>allocation_id</dt>
                      <dd class="font-mono text-xs text-slate-200">{{ allocation?.allocation_id || '—' }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>project</dt>
                      <dd>{{ allocation?.project || '—' }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>allocated_to</dt>
                      <dd>{{ allocation?.allocated_to || '—' }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>allocated_at</dt>
                      <dd>{{ formatDateTime(allocation?.allocated_at) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>status</dt>
                      <dd>{{ statusLabel(allocation?.status) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>release_reason</dt>
                      <dd>{{ allocation?.release_reason || '—' }}</dd>
                    </div>
                  </div>
                  <div v-else class="text-sm text-slate-400">—</div>
                </div>
              </details>

              <details v-if="showSaleSection" class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  售卖信息
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <div v-else class="grid gap-3 md:grid-cols-2">
                    <div class="drawer-field">
                      <dt>sold_at</dt>
                      <dd>{{ formatDateTime(sale?.sold_at) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>buyer</dt>
                      <dd>{{ sale?.buyer || sale?.sold_to || '—' }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>price</dt>
                      <dd>{{ formatPrice(sale?.price) }}</dd>
                    </div>
                    <div class="drawer-field">
                      <dt>note</dt>
                      <dd>{{ sale?.note || account?.sale_note || '—' }}</dd>
                    </div>
                  </div>
                </div>
              </details>

              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  事件日志
                </summary>
                <div class="drawer-body">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <div v-else class="text-sm text-slate-400">
                    暂无事件（AT-035 接入 ledger）
                  </div>
                </div>
              </details>

              <details class="glass-card overflow-hidden" open>
                <summary class="drawer-summary">
                  <span class="drawer-summary-marker">▼</span>
                  操作
                </summary>
                <div class="drawer-body space-y-4">
                  <div v-if="detailError" class="drawer-error">
                    {{ detailError }}
                  </div>
                  <template v-else>
                    <div
                      v-if="isMain"
                      class="rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
                    >
                      主号不可在此操作
                    </div>
                    <div v-else class="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3 text-sm text-slate-400">
                      分配仅限库存账号，释放仅限使用中账号，修复 OAuth 仅限失效账号。
                    </div>

                    <div v-if="actionError" class="drawer-error">
                      {{ actionError }}
                    </div>

                    <div class="flex flex-wrap gap-3">
                      <button
                        type="button"
                        class="btn-primary"
                        :disabled="buttonDisabled(!canAllocate, 'allocate')"
                        @click="openDialog('allocate')"
                      >
                        {{ actionLabel('allocate', '分配') }}
                      </button>
                      <button
                        type="button"
                        class="btn-secondary"
                        :disabled="buttonDisabled(!canRelease, 'release')"
                        @click="openDialog('release')"
                      >
                        {{ actionLabel('release', '释放') }}
                      </button>
                      <button
                        type="button"
                        class="btn-danger"
                        :disabled="buttonDisabled(!canMarkInvalid, 'mark-invalid')"
                        @click="openDialog('mark-invalid')"
                      >
                        {{ actionLabel('mark-invalid', '标记失效') }}
                      </button>
                      <button
                        type="button"
                        class="btn-secondary"
                        :disabled="buttonDisabled(!canRepairOauth, 'repair-oauth')"
                        @click="openDialog('repair-oauth')"
                      >
                        {{ actionLabel('repair-oauth', '修复 OAuth') }}
                      </button>
                    </div>
                  </template>
                </div>
              </details>
            </template>
          </div>
        </div>
      </div>
    </aside>

    <div
      v-if="activeDialog"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/75 p-4"
      @click.self="closeDialog"
    >
      <div class="glass-card w-full max-w-lg overflow-hidden">
        <div class="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h3 class="text-base font-semibold text-white">{{ dialogTitle }}</h3>
            <p class="mt-1 text-sm text-slate-400">{{ headerEmail }}</p>
          </div>
          <button
            type="button"
            class="btn-secondary h-10 w-10 shrink-0 px-0 text-lg"
            :disabled="dialogSubmitting"
            @click="closeDialog"
          >
            ×
          </button>
        </div>
        <div class="space-y-4 px-5 py-4">
          <div v-if="dialogError" class="drawer-error">
            {{ dialogError }}
          </div>

          <template v-if="activeDialog === 'allocate'">
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">project</span>
              <input
                v-model.trim="dialogForm.project"
                type="text"
                class="input-dark"
                placeholder="例如 gymbro"
                :disabled="dialogSubmitting"
              />
            </label>
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">allocated_to</span>
              <input
                v-model.trim="dialogForm.allocatedTo"
                type="text"
                class="input-dark"
                placeholder="例如 alice"
                :disabled="dialogSubmitting"
              />
            </label>
          </template>

          <template v-else-if="activeDialog === 'release'">
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">reason</span>
              <textarea
                v-model.trim="dialogForm.reason"
                class="textarea-dark"
                rows="4"
                placeholder="可留空，记录释放原因"
                :disabled="dialogSubmitting"
              />
            </label>
          </template>

          <template v-else-if="activeDialog === 'mark-invalid'">
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">reason</span>
              <select
                v-model="dialogForm.invalidReason"
                class="input-dark"
                :disabled="dialogSubmitting"
              >
                <option v-for="item in invalidReasonOptions" :key="item" :value="item">
                  {{ invalidReasonLabel(item) }}
                </option>
              </select>
            </label>
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">last_error</span>
              <textarea
                v-model.trim="dialogForm.lastError"
                class="textarea-dark"
                rows="4"
                placeholder="记录最近一次错误"
                :disabled="dialogSubmitting"
              />
            </label>
          </template>

          <template v-else-if="activeDialog === 'repair-oauth'">
            <label class="block space-y-2">
              <span class="text-sm text-slate-300">note</span>
              <textarea
                v-model.trim="dialogForm.note"
                class="textarea-dark"
                rows="4"
                placeholder="记录本次修复说明"
                :disabled="dialogSubmitting"
              />
            </label>
          </template>
        </div>
        <div class="flex justify-end gap-3 border-t border-white/10 px-5 py-4">
          <button
            type="button"
            class="btn-secondary"
            :disabled="dialogSubmitting"
            @click="closeDialog"
          >
            取消
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="dialogSubmitting"
            @click="submitDialog"
          >
            {{ dialogSubmitting ? '提交中...' : dialogSubmitLabel }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  email: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['close', 'action-done'])

const detail = ref(null)
const loading = ref(false)
const detailError = ref('')
const noticeText = ref('')
const noticeKind = ref('success')
const actionError = ref('')
const actionType = ref('')
const activeDialog = ref('')
const dialogSubmitting = ref(false)
const dialogError = ref('')
const invalidReasonOptions = [
  'auth_error',
  'account_deactivated',
  'token_revoked',
  'quota_exhausted',
]

const dialogForm = reactive({
  project: '',
  allocatedTo: '',
  reason: '',
  invalidReason: 'auth_error',
  lastError: '',
  note: '',
})

let fetchToken = 0

const account = computed(() => detail.value?.account || null)
const category = computed(() => normalizeKey(detail.value?.category || account.value?.category || ''))
const health = computed(() => detail.value?.health || {})
const allocation = computed(() => detail.value?.allocation || {})
const sale = computed(() => detail.value?.sale || {})
const credentials = computed(() => detail.value?.credentials || {})
const remote = computed(() => detail.value?.remote || {})

const headerEmail = computed(() => normalizeEmail(props.email) || '账号详情')
const registrationStatus = computed(() => normalizeKey(account.value?.registration_status))
const teamStatus = computed(() => normalizeKey(account.value?.team_status))
const usageStatus = computed(() => normalizeKey(account.value?.usage_status))
const healthStatus = computed(() => normalizeKey(health.value?.health_status || account.value?.health_status))
const isMain = computed(() => Boolean(account.value?.is_main_account || category.value === 'main'))
const isInvalid = computed(() => Boolean(health.value?.is_invalid))
const isInventory = computed(() => usageStatus.value === 'inventory' || category.value === 'inventory')
const isInUse = computed(() => usageStatus.value === 'in_use' || category.value === 'in_use')
const isValid = computed(() => healthStatus.value === 'valid' && !isInvalid.value)
const showSaleSection = computed(() => {
  return Boolean(
    sale.value?.sold_at
      || usageStatus.value === 'sold'
      || category.value === 'sold',
  )
})
const hasAllocation = computed(() => {
  return Object.values(allocation.value || {}).some((value) => value !== null && value !== undefined && value !== '')
})

const canAllocate = computed(() => !isMain.value && isInventory.value)
const canRelease = computed(() => !isMain.value && isInUse.value)
const canMarkInvalid = computed(() => !isMain.value && isValid.value)
const canRepairOauth = computed(() => !isMain.value && isInvalid.value)

const noticeClass = computed(() => {
  return noticeKind.value === 'error'
    ? 'border-rose-500/20 bg-rose-500/10 text-rose-200'
    : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
})

const categoryBadgeClass = computed(() => {
  return {
    main: 'border-amber-400/20 bg-amber-500/10 text-amber-200',
    inventory: 'border-cyan-400/20 bg-cyan-500/10 text-cyan-200',
    in_use: 'border-blue-400/20 bg-blue-500/10 text-blue-200',
    invalid: 'border-rose-400/20 bg-rose-500/10 text-rose-200',
    sold: 'border-violet-400/20 bg-violet-500/10 text-violet-200',
    not_registered: 'border-slate-500/20 bg-slate-500/10 text-slate-200',
    registered: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
  }[category.value] || 'border-slate-500/20 bg-slate-500/10 text-slate-200'
})

const credentialRows = computed(() => {
  return [
    { key: 'auth_file', label: 'auth_file', ...normalizeCredential(credentials.value?.auth_file) },
    { key: 'rt_auth_file', label: 'rt_auth_file', ...normalizeCredential(credentials.value?.rt_auth_file) },
    { key: 'session_auth_file', label: 'session_auth_file', ...normalizeCredential(credentials.value?.session_auth_file) },
  ]
})

const remoteRows = computed(() => {
  return [
    { key: 'cpa', label: 'CPA', status: normalizeKey(remote.value?.cpa?.status), block: remote.value?.cpa || {} },
    { key: 'sub2api', label: 'Sub2API', status: normalizeKey(remote.value?.sub2api?.status), block: remote.value?.sub2api || {} },
  ]
})

const dialogTitle = computed(() => {
  return {
    allocate: '分配库存账号',
    release: '释放使用中账号',
    'mark-invalid': '标记账号失效',
    'repair-oauth': '修复 OAuth',
  }[activeDialog.value] || '账号操作'
})

const dialogSubmitLabel = computed(() => {
  return {
    allocate: '确认分配',
    release: '确认释放',
    'mark-invalid': '确认标记',
    'repair-oauth': '确认修复',
  }[activeDialog.value] || '确认'
})

watch(
  () => [props.open, props.email],
  ([open, email], [prevOpen, prevEmail]) => {
    if (!open) {
      resetState()
      return
    }

    const normalizedEmail = normalizeEmail(email)
    if (!normalizedEmail) {
      detail.value = null
      detailError.value = ''
      loading.value = false
      return
    }

    if (!prevOpen || normalizeEmail(prevEmail) !== normalizedEmail) {
      void fetchDetail()
    }
  },
  { immediate: true },
)

function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase()
}

function normalizeKey(value) {
  return String(value || '').trim().toLowerCase()
}

function normalizeCredential(value) {
  if (!value || typeof value !== 'object') {
    return { path: '', exists: false, type: 'missing' }
  }
  return {
    path: String(value.path || ''),
    exists: Boolean(value.exists),
    type: String(value.type || 'missing'),
  }
}

function resetDialogForm() {
  dialogForm.project = ''
  dialogForm.allocatedTo = ''
  dialogForm.reason = ''
  dialogForm.invalidReason = 'auth_error'
  dialogForm.lastError = ''
  dialogForm.note = ''
}

function clearNotice() {
  noticeText.value = ''
  noticeKind.value = 'success'
}

function resetState() {
  fetchToken += 1
  detail.value = null
  loading.value = false
  detailError.value = ''
  actionError.value = ''
  actionType.value = ''
  activeDialog.value = ''
  dialogSubmitting.value = false
  dialogError.value = ''
  clearNotice()
  resetDialogForm()
}

async function fetchDetail(options = {}) {
  const email = normalizeEmail(props.email)
  if (!email || !props.open) return

  const token = ++fetchToken
  loading.value = true
  detail.value = null
  detailError.value = ''
  actionError.value = ''
  if (!options.preserveNotice) {
    clearNotice()
  }

  try {
    const data = await api.getAccountDetail(email)
    if (token !== fetchToken) return
    detail.value = data
  } catch (error) {
    if (token !== fetchToken) return
    detailError.value = error instanceof Error ? error.message : '拉取详情失败'
  } finally {
    if (token === fetchToken) {
      loading.value = false
    }
  }
}

function handleClose() {
  resetState()
  emit('close')
}

function openDialog(type) {
  if (isMain.value) return
  activeDialog.value = type
  dialogError.value = ''
  resetDialogForm()
}

function closeDialog() {
  if (dialogSubmitting.value) return
  activeDialog.value = ''
  dialogError.value = ''
  resetDialogForm()
}

function buttonDisabled(disabled, type) {
  return Boolean(disabled || isMain.value || dialogSubmitting.value || actionType.value === type)
}

function actionLabel(type, label) {
  return actionType.value === type ? `${label}中...` : label
}

async function submitDialog() {
  const email = normalizeEmail(props.email)
  if (!email || !activeDialog.value || dialogSubmitting.value) return

  dialogSubmitting.value = true
  dialogError.value = ''
  actionError.value = ''
  actionType.value = activeDialog.value

  try {
    let response
    if (activeDialog.value === 'allocate') {
      response = await api.allocateAccount(email, {
        project: dialogForm.project,
        allocated_to: dialogForm.allocatedTo,
      })
    } else if (activeDialog.value === 'release') {
      response = await api.releaseAccount(email, {
        reason: dialogForm.reason,
      })
    } else if (activeDialog.value === 'mark-invalid') {
      response = await api.markAccountInvalid(email, {
        reason: dialogForm.invalidReason,
        last_error: dialogForm.lastError,
      })
    } else if (activeDialog.value === 'repair-oauth') {
      response = await api.repairAccountOauth(email, {
        note: dialogForm.note,
      })
    } else {
      return
    }

    noticeKind.value = 'success'
    noticeText.value = buildSuccessMessage(activeDialog.value, response)
    closeDialog()
    emit('action-done')
    await fetchDetail({ preserveNotice: true })
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '操作失败'
    actionError.value = dialogError.value
    noticeText.value = ''
  } finally {
    dialogSubmitting.value = false
    actionType.value = ''
  }
}

function buildSuccessMessage(type, response) {
  if (response && typeof response.message === 'string' && response.message.trim()) {
    return response.message
  }
  return {
    allocate: '分配完成',
    release: '释放完成',
    'mark-invalid': '已标记失效',
    'repair-oauth': 'OAuth 修复完成',
  }[type] || '操作完成'
}

function categoryLabel(value) {
  return {
    main: '主号',
    inventory: '库存',
    in_use: '使用中',
    invalid: '失效',
    sold: '已售',
    not_registered: '未注册',
    registered: '已注册',
  }[normalizeKey(value)] || (value ? String(value) : '未知')
}

function statusLabel(value) {
  return {
    planned: 'planned',
    mail_created: 'mail_created',
    registering: 'registering',
    registered: 'registered',
    register_failed: 'register_failed',
    abandoned: 'abandoned',
    unknown: 'unknown',
    valid: 'valid',
    quota_exhausted: 'quota_exhausted',
    auth_expired: 'auth_expired',
    invalid: 'invalid',
    deactivated: 'deactivated',
    risk_blocked: 'risk_blocked',
    sync_error: 'sync_error',
    normal: 'normal',
    inventory: 'inventory',
    in_use: 'in_use',
    reserved: 'reserved',
    sold: 'sold',
    self_use: 'self_use',
    quarantine: 'quarantine',
    active: 'active',
    standby: 'standby',
    pending_invite: 'pending_invite',
    removed: 'removed',
    external: 'external',
    owner: 'owner',
    released: 'released',
  }[normalizeKey(value)] || (value ? String(value) : '—')
}

function invalidReasonLabel(value) {
  return {
    auth_error: 'auth_error',
    account_deactivated: 'account_deactivated',
    token_revoked: 'token_revoked',
    quota_exhausted: 'quota_exhausted',
  }[normalizeKey(value)] || (value ? String(value) : '—')
}

function remoteStatusLabel(value) {
  return {
    present: 'present',
    missing: 'missing',
    failed: 'failed',
    disabled: 'disabled',
    unknown: 'unknown',
    uploaded: 'uploaded',
    skipped_sold: 'skipped_sold',
    skipped_invalid: 'skipped_invalid',
  }[normalizeKey(value)] || (value ? String(value) : 'unknown')
}

function remoteStatusClass(value) {
  return {
    present: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
    uploaded: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
    missing: 'border-amber-400/20 bg-amber-500/10 text-amber-200',
    failed: 'border-rose-400/20 bg-rose-500/10 text-rose-200',
    disabled: 'border-slate-500/20 bg-slate-500/10 text-slate-200',
    skipped_sold: 'border-violet-400/20 bg-violet-500/10 text-violet-200',
    skipped_invalid: 'border-rose-400/20 bg-rose-500/10 text-rose-200',
    unknown: 'border-slate-500/20 bg-slate-500/10 text-slate-200',
  }[normalizeKey(value)] || 'border-slate-500/20 bg-slate-500/10 text-slate-200'
}

function boolLabel(value) {
  return value ? '是' : '否'
}

function formatDateTime(value) {
  if (value === null || value === undefined || value === '') return '—'

  let numeric = null
  if (typeof value === 'number' && Number.isFinite(value)) {
    numeric = value
  } else if (typeof value === 'string' && /^\d+(\.\d+)?$/.test(value.trim())) {
    numeric = Number(value)
  }

  let date
  if (numeric !== null) {
    const millis = numeric > 1e12 ? numeric : numeric * 1000
    date = new Date(millis)
  } else {
    date = new Date(value)
  }

  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  const second = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`
}

function formatPrice(value) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}
</script>

<style scoped>
details > summary::-webkit-details-marker {
  display: none;
}

details > summary {
  list-style: none;
}

.drawer-summary {
  display: flex;
  cursor: pointer;
  align-items: center;
  gap: 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 1rem 1.25rem;
  color: rgb(248 250 252);
  font-size: 0.95rem;
  font-weight: 600;
}

.drawer-summary-marker {
  color: rgb(148 163 184);
  font-size: 0.75rem;
}

.drawer-body {
  padding: 1rem 1.25rem 1.25rem;
}

.drawer-field dt {
  color: rgb(148 163 184);
  font-size: 0.75rem;
  margin-bottom: 0.25rem;
}

.drawer-field dd {
  color: rgb(226 232 240);
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0;
}

.drawer-error {
  border: 1px solid rgba(251, 113, 133, 0.2);
  background: rgba(244, 63, 94, 0.1);
  color: rgb(254 205 211);
  border-radius: 1rem;
  padding: 0.875rem 1rem;
  font-size: 0.9rem;
}
</style>
