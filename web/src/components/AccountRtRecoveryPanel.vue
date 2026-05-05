<template>
  <div class="space-y-5">
    <div class="rounded-lg border border-gray-800 bg-gray-900 p-5">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-white">RT 恢复分类</h3>
          <p class="mt-1 text-sm leading-6 text-gray-400">
            找出注册已完成但没有 OAuth RT 的账号，以及 401 后需要重新获取 RT 的账号。启动恢复时会先重建 MoEmail 永久邮箱，再检查 Deactivated 邮件；命中后标记失效并释放 Team 席位，不继续获取 RT。
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-lg border px-4 py-2 text-sm font-medium transition"
            :class="busy
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-cyan-500/40 bg-cyan-600/10 text-cyan-200 hover:bg-cyan-600/20'"
            :disabled="busy"
            @click="runScan"
          >
            {{ busy && activeAction === 'scan' ? '扫描中...' : '扫描 RT 状态' }}
          </button>
          <button
            type="button"
            class="rounded-lg border px-4 py-2 text-sm font-medium transition"
            :class="!canStartRecovery || busy
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-emerald-500/40 bg-emerald-600/10 text-emerald-200 hover:bg-emerald-600/20'"
            :disabled="!canStartRecovery || busy"
            @click="startSelectedRecovery"
          >
            {{ busy && activeAction === 'recover' ? '启动中...' : '恢复选中 RT' }}
          </button>
          <button
            type="button"
            class="rounded-lg border px-4 py-2 text-sm font-medium transition"
            :class="!canMarkDeactivated || busy
              ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
              : 'border-rose-500/40 bg-rose-600/10 text-rose-200 hover:bg-rose-600/20'"
            :disabled="!canMarkDeactivated || busy"
            @click="markDeactivated"
          >
            {{ busy && activeAction === 'mark' ? '标记中...' : '标记 Deactivated' }}
          </button>
        </div>
      </div>

      <div v-if="error" class="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
        {{ error }}
      </div>
      <div v-if="message" class="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
        {{ message }}
      </div>

      <div v-if="hasReport" class="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <div
          v-for="card in summaryCards"
          :key="card.key"
          class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3"
        >
          <div class="text-xs text-gray-500">{{ card.label }}</div>
          <div class="mt-1 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
        </div>
      </div>
    </div>

    <div v-if="hasReport" class="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
      <div class="rounded-lg border border-gray-800 bg-gray-900">
        <div class="flex flex-col gap-3 border-b border-gray-800 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div class="text-sm font-semibold text-white">可恢复账号</div>
            <div class="mt-1 text-xs text-gray-500">缺 RT 和 401 账号会先重建 MoEmail、查 Deactivated，再重新跑账号 OAuth；不会上传远端。</div>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="recoverableRows.length === 0 || busy"
              @click="selectAllRecoverable"
            >
              全选
            </button>
            <button
              type="button"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="selectedEmails.length === 0 || busy"
              @click="selectedEmails = []"
            >
              清空
            </button>
          </div>
        </div>
        <div v-if="recoverableRows.length === 0" class="px-4 py-8 text-sm text-gray-500">
          没有发现可恢复账号。
        </div>
        <div v-else class="max-h-[520px] divide-y divide-gray-800/70 overflow-y-auto">
          <label
            v-for="row in recoverableRows"
            :key="row.email"
            class="flex cursor-pointer items-start gap-3 px-4 py-3 hover:bg-white/[0.03]"
          >
            <input
              v-model="selectedEmails"
              type="checkbox"
              :value="row.email"
              class="mt-1 h-4 w-4 rounded border-gray-700 bg-gray-950 text-cyan-500"
            />
            <span class="min-w-0 flex-1">
              <span class="block break-all font-mono text-sm text-gray-100">{{ row.email }}</span>
              <span class="mt-1 flex flex-wrap items-center gap-2 text-xs">
                <span class="rounded-full border px-2 py-0.5" :class="categoryPillClass(row.category)">
                  {{ categoryLabel(row.category) }}
                </span>
                <span class="text-gray-500">{{ row.has_session ? '有 session 备份' : '无 session 备份' }}</span>
                <span v-if="row.sync_disabled" class="text-amber-300">已停止同步，恢复会 force</span>
              </span>
              <span class="mt-1 block text-xs text-gray-500">{{ row.reason }}</span>
            </span>
          </label>
        </div>
      </div>

      <div class="space-y-5">
        <div class="rounded-lg border border-gray-800 bg-gray-900">
          <div class="border-b border-gray-800 px-4 py-3">
            <div class="text-sm font-semibold text-white">Deactivated 账号</div>
            <div class="mt-1 text-xs text-gray-500">这些账号会被标记为 unavailable/deactivated，并禁用同步。</div>
          </div>
          <div v-if="deactivatedRows.length === 0" class="px-4 py-6 text-sm text-gray-500">
            没有发现 Deactivated 标记。
          </div>
          <div v-else class="max-h-72 divide-y divide-gray-800/70 overflow-y-auto">
            <div
              v-for="row in deactivatedRows"
              :key="row.email"
              class="px-4 py-3"
            >
              <div class="break-all font-mono text-sm text-rose-100">{{ row.email }}</div>
              <div class="mt-1 text-xs text-gray-500">{{ row.last_error || row.unavailable_reason || row.reason }}</div>
            </div>
          </div>
        </div>

        <div v-if="task" class="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <div class="text-sm font-semibold text-white">恢复任务</div>
          <div class="mt-3 grid gap-2 text-xs text-gray-400">
            <div>任务 ID：<span class="font-mono text-gray-200">{{ task.task_id }}</span></div>
            <div>命令：<span class="font-mono text-gray-200">{{ task.command }}</span></div>
            <div>状态：<span class="text-gray-200">{{ task.status || 'pending' }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits(['refresh'])

const report = ref(null)
const selectedEmails = ref([])
const busy = ref(false)
const activeAction = ref('')
const error = ref('')
const message = ref('')
const task = ref(null)

const hasReport = computed(() => Boolean(report.value))
const allRows = computed(() => report.value?.items || [])
const recoverableRows = computed(() => report.value?.recoverable || [])
const deactivatedRows = computed(() => report.value?.deactivated || [])
const canStartRecovery = computed(() => selectedEmails.value.length > 0)
const canMarkDeactivated = computed(() => deactivatedRows.value.length > 0)

const summaryCards = computed(() => {
  const summary = report.value?.summary || {}
  return [
    { key: 'total', label: '总账号', value: report.value?.total_accounts || 0, color: 'text-white' },
    { key: 'recoverable', label: '可恢复', value: report.value?.recoverable_count || 0, color: 'text-emerald-300' },
    { key: 'missing', label: '注册缺 RT', value: summary.rt_missing_registered || 0, color: 'text-cyan-300' },
    { key: '401', label: '401 重取 RT', value: summary.rt_401_reauth_needed || 0, color: 'text-amber-300' },
    { key: 'deactivated', label: 'Deactivated', value: report.value?.deactivated_count || 0, color: 'text-rose-300' },
    { key: 'ready', label: '已有 RT', value: summary.rt_ready || 0, color: 'text-slate-300' },
  ]
})

function categoryLabel(category) {
  const labels = {
    rt_missing_registered: '注册缺 RT',
    rt_401_reauth_needed: '401 重取 RT',
    deactivated_invalid: 'Deactivated',
    rt_ready: '已有 RT',
    not_registered: '未注册',
    sold: '已售',
    main: '主号',
  }
  return labels[category] || category || '未知'
}

function categoryPillClass(category) {
  if (category === 'rt_401_reauth_needed') return 'border-amber-400/30 bg-amber-500/10 text-amber-200'
  if (category === 'rt_missing_registered') return 'border-cyan-400/30 bg-cyan-500/10 text-cyan-200'
  return 'border-gray-700 bg-gray-800 text-gray-300'
}

function selectAllRecoverable() {
  selectedEmails.value = recoverableRows.value.map((row) => row.email)
}

async function runAction(name, fn) {
  busy.value = true
  activeAction.value = name
  error.value = ''
  message.value = ''
  try {
    await fn()
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    busy.value = false
    activeAction.value = ''
  }
}

async function runScan() {
  await runAction('scan', async () => {
    const data = await api.scanRtRecovery()
    report.value = data.report
    selectedEmails.value = (data.report?.recoverable || []).map((row) => row.email)
    task.value = null
  })
}

async function startSelectedRecovery() {
  const emails = selectedEmails.value.slice()
  if (!emails.length) return
  await runAction('recover', async () => {
    task.value = await api.startRtRecovery({
      emails,
      force: true,
      check_quota_snapshot: true,
      max_accounts: 200,
    })
    message.value = `已启动 ${emails.length} 个账号的 RT 恢复任务`
    emit('refresh')
  })
}

async function markDeactivated() {
  await runAction('mark', async () => {
    const emails = deactivatedRows.value.map((row) => row.email)
    const data = await api.markRtRecoveryDeactivated({ emails })
    message.value = data.message || `已标记 ${emails.length} 个账号`
    await runScan()
    emit('refresh')
  })
}
</script>
