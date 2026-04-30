<template>
  <div class="space-y-6">
    <h2 class="text-xl font-bold text-white mb-2">账号池操作</h2>
    <p class="text-sm text-gray-400 mb-6">
      这里集中放轮转、检查、补满、添加、清理等会直接影响账号池状态的操作。
    </p>
    <TaskPanel
      mode="pool"
      :running-task="runningTask"
      :admin-status="adminStatus"
      :parallel-workers="parallelWorkers"
      @task-started="$emit('task-started')"
      @refresh="$emit('refresh')"
    />

    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-white">补账号完整流程</h3>
          <p class="text-sm text-gray-400 mt-1">
            直注注册、Team 入席、OAuth 认证、CPA JSON 上传在一个任务里执行，并保留每个账号的阶段记录。
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <select
            v-model.number="parallelWorkers"
            :disabled="batchDisabled"
            class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
          >
            <option :value="1">1 个窗口</option>
            <option :value="2">2 个窗口</option>
            <option :value="3">3 个窗口</option>
          </select>
          <select
            v-model="joinMode"
            :disabled="batchDisabled"
            class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
          >
            <option value="direct">直注入席</option>
            <option value="invite">邀请入席</option>
          </select>
          <button
            @click="startBatch"
            :disabled="batchDisabled || submitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="batchDisabled || submitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-cyan-600 text-white border-cyan-500 hover:bg-cyan-500'"
          >
            {{ submitting ? '提交中...' : '开始 100 个任务' }}
          </button>
          <button
            @click="pauseActiveRun"
            :disabled="!canPause || pauseSubmitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="!canPause || pauseSubmitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-amber-600/10 text-amber-300 border-amber-500/30 hover:bg-amber-600/20'"
          >
            {{ pauseSubmitting ? '提交中...' : '暂停' }}
          </button>
          <button
            @click="resumeActiveRun"
            :disabled="!canResume || resumeSubmitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="!canResume || resumeSubmitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'"
          >
            {{ resumeSubmitting ? '提交中...' : '恢复' }}
          </button>
          <button
            @click="pushCpa"
            :disabled="syncDisabled || syncSubmitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="syncDisabled || syncSubmitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'"
          >
            {{ syncSubmitting ? '推送中...' : 'CPA 推送云端' }}
          </button>
          <button
            @click="pushSub2api"
            :disabled="syncDisabled || sub2apiSubmitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="syncDisabled || sub2apiSubmitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-indigo-600/10 text-indigo-300 border-indigo-500/30 hover:bg-indigo-600/20'"
          >
            {{ sub2apiSubmitting ? '推送中...' : 'Sub2API 推送云端' }}
          </button>
          <button
            @click="pushOAuth"
            :disabled="syncDisabled || oauthSubmitting"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="syncDisabled || oauthSubmitting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-blue-600/10 text-blue-300 border-blue-500/30 hover:bg-blue-600/20'"
          >
            {{ oauthSubmitting ? '推送中...' : 'OAuth 凭证推送' }}
          </button>
          <button
            @click="loadRuns"
            :disabled="loadingRuns"
            class="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            {{ loadingRuns ? '刷新中...' : '刷新记录' }}
          </button>
        </div>
      </div>

      <div v-if="!adminReady" class="mt-4 px-4 py-3 rounded-lg text-sm border bg-amber-500/10 text-amber-300 border-amber-500/20">
        请先在「配置面板」页完成管理员登录后，再启动批量任务。
      </div>
      <div v-if="message" class="mt-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div v-if="activeRun" class="mt-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <div v-for="card in runCards" :key="card.label" class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">{{ card.label }}</div>
          <div class="mt-1 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
        </div>
      </div>
      <div v-if="activeRun" class="mt-3 h-2 rounded-full bg-gray-800 overflow-hidden">
        <div class="h-full bg-cyan-500 transition-all" :style="{ width: runProgressWidth }"></div>
      </div>

      <div v-if="activeRun && workerStats.length" class="mt-4 rounded-lg border border-gray-800 bg-gray-950/40 overflow-hidden">
        <div class="px-3 py-2 bg-gray-950/60 border-b border-gray-800 flex items-center justify-between">
          <div class="text-sm font-medium text-white">窗口实时状态</div>
          <div class="text-xs text-gray-500">按窗口统计成功率与当前状态</div>
        </div>
        <div class="p-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div
            v-for="worker in workerStats"
            :key="worker.workerIndex"
            class="rounded-lg border border-gray-800 bg-gray-900/70 px-3 py-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="text-sm font-medium text-white">窗口 {{ worker.workerIndex }}</div>
              <span
                class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium border"
                :class="workerStatusClass(worker.status)"
              >
                {{ workerStatusLabel(worker.status) }}
              </span>
            </div>
            <div class="mt-2 text-xs text-gray-400">
              成功 {{ worker.success }} / {{ worker.attempted }} · 失败 {{ worker.failed }}
            </div>
            <div class="mt-1 text-sm text-cyan-300">
              成功率 {{ formatPercent(worker.successRate) }}%
            </div>
            <div class="mt-1 text-xs text-gray-500">
              当前阶段：{{ stageLabel(worker.stage) }}
            </div>
          </div>
        </div>
      </div>

      <div class="mt-5 grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div class="rounded-lg border border-gray-800 overflow-hidden">
          <div class="px-3 py-2 bg-gray-950/50 border-b border-gray-800 text-sm font-medium text-white">运行记录</div>
          <div v-if="runs.length === 0" class="px-3 py-6 text-sm text-gray-500 text-center">暂无记录</div>
          <button
            v-for="run in runs"
            :key="run.run_id"
            @click="selectedRunId = run.run_id"
            class="w-full px-3 py-3 text-left border-b border-gray-800/70 hover:bg-gray-800/40 transition"
            :class="selectedRunId === run.run_id ? 'bg-gray-800/70' : 'bg-gray-900'"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono text-xs text-gray-300">{{ run.run_id }}</span>
              <span class="text-xs" :class="runStatusClass(run.status)">{{ runStatusLabel(run.status) }}</span>
            </div>
            <div class="mt-1 text-xs text-gray-500">
              {{ joinModeLabel(run.join_mode) }} · {{ run.success_count || 0 }}/{{ run.target || 100 }}
            </div>
            <div class="mt-1 text-xs text-gray-600">{{ formatTime(run.created_at) }}</div>
          </button>
        </div>

        <div class="rounded-lg border border-gray-800 overflow-hidden">
          <div class="px-3 py-2 bg-gray-950/50 border-b border-gray-800 flex items-center justify-between">
            <div class="text-sm font-medium text-white">账号明细</div>
            <div v-if="activeRun" class="text-xs text-gray-500">
              第 {{ activeRun.current_batch || 1 }} 组 · 每组 {{ activeRun.batch_size || 20 }}
            </div>
          </div>
          <div v-if="!activeRun" class="px-3 py-8 text-sm text-gray-500 text-center">请选择一条运行记录</div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-gray-400 text-left border-b border-gray-800">
                  <th class="px-3 py-3 font-medium">邮箱</th>
                  <th class="px-3 py-3 font-medium">组</th>
                  <th class="px-3 py-3 font-medium">窗口</th>
                  <th class="px-3 py-3 font-medium">阶段</th>
                  <th class="px-3 py-3 font-medium">状态</th>
                  <th class="px-3 py-3 font-medium">等级</th>
                  <th class="px-3 py-3 font-medium">CPA JSON</th>
                  <th class="px-3 py-3 font-medium">错误</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="visibleAccounts.length === 0">
                  <td colspan="8" class="px-3 py-8 text-center text-gray-500">暂无账号记录</td>
                </tr>
                <tr
                  v-for="acc in visibleAccounts"
                  :key="`${acc.email}-${acc.started_at}`"
                  class="border-b border-gray-800/50 hover:bg-gray-800/30 transition"
                >
                  <td class="px-3 py-3 font-mono text-xs text-gray-200">{{ acc.email }}</td>
                  <td class="px-3 py-3 text-gray-400">{{ acc.batch_index || '-' }}</td>
                  <td class="px-3 py-3 text-gray-400">{{ acc.worker_index || '-' }}</td>
                  <td class="px-3 py-3 text-gray-300">{{ stageLabel(acc.stage) }}</td>
                  <td class="px-3 py-3">
                    <span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium border" :class="accountStatusClass(acc.status)">
                      {{ accountStatusLabel(acc.status) }}
                    </span>
                  </td>
                  <td class="px-3 py-3">
                    <span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium border" :class="errorLevelClass(acc.error_level)">
                      {{ errorLevelLabel(acc.error_level) }}
                    </span>
                  </td>
                  <td class="px-3 py-3 text-xs text-gray-400">
                    {{ acc.cpa_uploaded ? (acc.auth_name || '已上传') : '-' }}
                  </td>
                  <td class="px-3 py-3 text-xs max-w-xs truncate" :class="acc.error_message ? 'text-red-300' : 'text-gray-500'">
                    {{ acc.error_message || '-' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="activeRun?.fatal_error" class="px-3 py-3 text-sm border-t border-gray-800 bg-red-500/10 text-red-300">
            {{ activeRun.fatal_error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import TaskPanel from './TaskPanel.vue'
import { api } from '../api.js'

const props = defineProps({
  runningTask: Object,
  adminStatus: Object,
})

const emit = defineEmits(['task-started', 'refresh'])

const joinMode = ref('direct')
const parallelWorkers = ref(1)
const runs = ref([])
const selectedRunId = ref('')
const loadingRuns = ref(false)
const submitting = ref(false)
const pauseSubmitting = ref(false)
const resumeSubmitting = ref(false)
const syncSubmitting = ref(false)
const sub2apiSubmitting = ref(false)
const oauthSubmitting = ref(false)
const message = ref('')
const messageClass = ref('')
let refreshTimer = null

const adminReady = computed(() => !!props.adminStatus?.configured)
const batchDisabled = computed(() => !!props.runningTask || !adminReady.value)
const syncDisabled = computed(() => !!props.runningTask)
const activeRun = computed(() => {
  const runningRunId = props.runningTask?.command === 'cpa-batch' ? props.runningTask?.params?.run_id : ''
  const preferred = runningRunId || selectedRunId.value
  return runs.value.find(run => run.run_id === preferred) || runs.value[0] || null
})
const hasRunningRun = computed(() => runs.value.some(run => run.status === 'running'))
const canPause = computed(() => activeRun.value?.status === 'running')
const canResume = computed(() => {
  const run = activeRun.value
  if (!run || props.runningTask) return false
  if (!['paused', 'partial', 'failed'].includes(run.status)) return false
  return (run.success_count || 0) < (run.target || 100)
})
const visibleAccounts = computed(() => {
  return (activeRun.value?.accounts || [])
    .filter(acc => acc.status !== 'replaced')
    .slice()
    .sort((a, b) => {
      if ((a.batch_index || 0) !== (b.batch_index || 0)) return (a.batch_index || 0) - (b.batch_index || 0)
      return (a.started_at || 0) - (b.started_at || 0)
    })
})
const runProgressWidth = computed(() => {
  const run = activeRun.value
  if (!run) return '0%'
  const target = run.target || 100
  const pct = Math.min(100, Math.round(((run.success_count || 0) / target) * 100))
  return `${pct}%`
})
const workerStats = computed(() => {
  const run = activeRun.value
  if (!run) return []

  const accounts = (run.accounts || []).filter(acc => acc.status !== 'replaced')
  const workerAccounts = accounts.filter(acc => toWorkerIndex(acc.worker_index) > 0)
  const knownIndexes = workerAccounts.map(acc => toWorkerIndex(acc.worker_index))

  let workerCount = Number(run.parallel_workers || 0)
  if (!Number.isFinite(workerCount) || workerCount <= 0) {
    workerCount = knownIndexes.length ? Math.max(...knownIndexes) : 1
  }
  workerCount = Math.max(1, Math.floor(workerCount))
  if (knownIndexes.length) {
    workerCount = Math.max(workerCount, Math.max(...knownIndexes))
  }

  const stats = []
  for (let workerIndex = 1; workerIndex <= workerCount; workerIndex += 1) {
    const items = workerAccounts.filter(acc => toWorkerIndex(acc.worker_index) === workerIndex)
    const attempted = items.length
    const success = items.filter(acc => acc.status === 'success').length
    const failed = items.filter(acc => acc.status === 'failed').length
    const running = items.filter(acc => acc.status === 'running').length
    const pending = items.filter(acc => acc.status === 'pending').length
    const latest = items
      .slice()
      .sort((a, b) => (b.started_at || 0) - (a.started_at || 0))[0]

    stats.push({
      workerIndex,
      attempted,
      success,
      failed,
      running,
      pending,
      stage: latest?.stage || '',
      successRate: attempted > 0 ? (success * 100) / attempted : 0,
      status: resolveWorkerStatus({
        runStatus: run.status || '',
        attempted,
        success,
        failed,
        running,
        pending,
      }),
    })
  }

  return stats
})
const runCards = computed(() => {
  const run = activeRun.value || {}
  const target = run.target || 100
  return [
    { label: '目标', value: target, color: 'text-white' },
    { label: '成功', value: run.success_count || 0, color: 'text-emerald-300' },
    { label: '失败', value: run.failed_count || 0, color: 'text-red-300' },
    { label: '已尝试', value: run.attempted_count || 0, color: 'text-cyan-300' },
    { label: '进度', value: runProgressWidth.value, color: 'text-blue-300' },
  ]
})

watch(
  () => props.runningTask,
  () => {
    loadRuns()
  },
)

watch(
  [() => props.runningTask, hasRunningRun],
  () => {
    manageTimer()
  },
  { immediate: true },
)

onMounted(() => {
  loadRuns()
  manageTimer()
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})

function manageTimer() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (props.runningTask?.command === 'cpa-batch' || hasRunningRun.value) {
    refreshTimer = window.setInterval(loadRuns, 3000)
  }
}

function setMessage(text, type = 'success') {
  message.value = text
  messageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    runs.value = await api.getCpaBatchRuns()
    if (!selectedRunId.value && runs.value.length) {
      selectedRunId.value = runs.value[0].run_id
    }
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    loadingRuns.value = false
  }
}

async function startBatch() {
  if (batchDisabled.value || submitting.value) return
  submitting.value = true
  try {
    const result = await api.startCpaBatch(joinMode.value, null, null, parallelWorkers.value)
    selectedRunId.value = result.params?.run_id || ''
    setMessage(`批量任务已提交: ${result.task_id}`)
    emit('task-started')
    await loadRuns()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    submitting.value = false
  }
}

async function pauseActiveRun() {
  if (!canPause.value || pauseSubmitting.value) return
  pauseSubmitting.value = true
  try {
    await api.pauseCpaBatchRun(activeRun.value.run_id)
    setMessage('已请求暂停，当前账号阶段结束后会停止继续新账号')
    await loadRuns()
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    pauseSubmitting.value = false
  }
}

async function resumeActiveRun() {
  if (!canResume.value || resumeSubmitting.value) return
  resumeSubmitting.value = true
  try {
    const result = await api.resumeCpaBatchRun(activeRun.value.run_id)
    setMessage(`恢复任务已提交: ${result.task_id}`)
    emit('task-started')
    await loadRuns()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    resumeSubmitting.value = false
  }
}

async function pushCpa() {
  if (syncDisabled.value || syncSubmitting.value) return
  syncSubmitting.value = true
  try {
    const result = await api.postSyncCpa()
    setMessage(result.message || 'CPA 已推送到云端')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    syncSubmitting.value = false
  }
}

async function pushSub2api() {
  if (syncDisabled.value || sub2apiSubmitting.value) return
  sub2apiSubmitting.value = true
  try {
    const result = await api.postSyncSub2api()
    setMessage(result.message || 'Sub2API 已推送到云端')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    sub2apiSubmitting.value = false
  }
}

async function pushOAuth() {
  if (syncDisabled.value || oauthSubmitting.value) return
  oauthSubmitting.value = true
  try {
    const result = await api.postSyncSavedMainCodex()
    setMessage(result.message || 'OAuth 凭证已推送到已启用云端')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    oauthSubmitting.value = false
  }
}

function joinModeLabel(value) {
  return value === 'invite' ? '邀请' : '直注'
}

function runStatusLabel(value) {
  return { running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', partial: '部分完成' }[value] || value || '-'
}

function runStatusClass(value) {
  return {
    running: 'text-yellow-300',
    paused: 'text-amber-300',
    completed: 'text-emerald-300',
    failed: 'text-red-300',
    partial: 'text-amber-300',
  }[value] || 'text-gray-400'
}

function accountStatusLabel(value) {
  return { pending: '等待', running: '进行中', success: '成功', failed: '失败' }[value] || value || '-'
}

function accountStatusClass(value) {
  return {
    pending: 'bg-gray-500/10 text-gray-300 border-gray-500/20',
    running: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20',
    success: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    failed: 'bg-red-500/10 text-red-300 border-red-500/20',
  }[value] || 'bg-gray-500/10 text-gray-300 border-gray-500/20'
}

function errorLevelLabel(value) {
  return { info: '信息', warn: '警告', error: '错误', fatal: '严重' }[value] || '信息'
}

function errorLevelClass(value) {
  return {
    info: 'bg-gray-500/10 text-gray-300 border-gray-500/20',
    warn: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    error: 'bg-red-500/10 text-red-300 border-red-500/20',
    fatal: 'bg-red-700/20 text-red-200 border-red-500/30',
  }[value] || 'bg-gray-500/10 text-gray-300 border-gray-500/20'
}

function toWorkerIndex(value) {
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return 0
  return Math.floor(num)
}

function resolveWorkerStatus({ runStatus, attempted, success, failed, running, pending }) {
  if (running > 0) return 'running'
  if (pending > 0) return 'pending'
  if (attempted === 0) {
    return runStatus === 'running' ? 'waiting' : 'idle'
  }
  if (runStatus === 'paused') return 'paused'
  if (runStatus === 'failed') return 'failed'
  if (runStatus === 'partial') return 'partial'
  if (runStatus === 'completed') {
    return failed > 0 ? 'partial' : 'completed'
  }
  if (success > 0 && failed > 0) return 'partial'
  if (failed > 0 && success === 0) return 'failed'
  if (success > 0) return 'completed'
  return 'idle'
}

function workerStatusLabel(value) {
  return {
    running: '运行中',
    pending: '等待中',
    waiting: '待分配',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    partial: '部分成功',
    idle: '空闲',
  }[value] || value || '-'
}

function workerStatusClass(value) {
  return {
    running: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20',
    pending: 'bg-gray-500/10 text-gray-300 border-gray-500/20',
    waiting: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
    paused: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    completed: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    failed: 'bg-red-500/10 text-red-300 border-red-500/20',
    partial: 'bg-orange-500/10 text-orange-300 border-orange-500/20',
    idle: 'bg-gray-500/10 text-gray-300 border-gray-500/20',
  }[value] || 'bg-gray-500/10 text-gray-300 border-gray-500/20'
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '0.0'
  return num.toFixed(1)
}

function stageLabel(value) {
  return {
    create_email: '创建邮箱',
    email_created: '邮箱已保存',
    register: '注册',
    register_retry: '注册重试',
    cpa_retry: 'CPA 重试',
    invite_sent: '已邀请',
    team_joined: '已入席',
    cpa_queued: '等待 CPA',
    cpa_auth: 'CPA 认证',
    oauth: 'OAuth',
    quota_check: '额度检查',
    cpa_upload: 'CPA 上传',
    completed: '完成',
    interrupted: '已中断',
  }[value] || value || '-'
}

function formatTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
</script>
