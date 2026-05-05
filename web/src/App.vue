<template>
  <!-- 初始配置页 -->
  <SetupPage v-if="needSetup" @configured="onSetupDone" />

  <!-- 登录页 -->
  <div v-else-if="!authenticated" class="relative min-h-screen overflow-hidden">
    <div class="pointer-events-none absolute inset-0">
      <div class="absolute left-[-8rem] top-[-8rem] h-72 w-72 rounded-full bg-blue-500/20 blur-3xl"></div>
      <div class="absolute bottom-[-10rem] right-[-5rem] h-80 w-80 rounded-full bg-cyan-500/15 blur-3xl"></div>
    </div>

    <div class="relative mx-auto flex min-h-screen max-w-6xl items-center px-4 py-10">
      <div class="grid w-full items-center gap-8 lg:grid-cols-[1.2fr_0.8fr]">
        <div class="hidden lg:block">
          <div class="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-500/10 px-4 py-2 text-sm text-blue-200">
            <span class="inline-block h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_16px_rgba(34,211,238,0.9)]"></span>
            AutoTeam Control Center
          </div>
          <h1 class="max-w-2xl text-5xl font-bold leading-tight text-white">
            更顺手一点的
            <span class="bg-gradient-to-r from-blue-300 via-cyan-300 to-sky-400 bg-clip-text text-transparent">Team 管理面板</span>
          </h1>
          <p class="mt-5 max-w-2xl text-lg leading-8 text-slate-300">
            一个入口处理账号池、同步、OAuth、配置和巡检。先用 API Key 登录，后面的运行配置都可以在面板里直接改。
          </p>
          <div class="mt-8 grid max-w-2xl grid-cols-3 gap-4">
            <div class="glass-card-soft p-4">
              <div class="text-2xl">🧩</div>
              <div class="mt-3 text-sm font-medium text-white">统一配置</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">可视化编辑 + 源文件编辑</div>
            </div>
            <div class="glass-card-soft p-4">
              <div class="text-2xl">🔄</div>
              <div class="mt-3 text-sm font-medium text-white">自动巡检</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">阈值触发轮转与补位</div>
            </div>
            <div class="glass-card-soft p-4">
              <div class="text-2xl">🔐</div>
              <div class="mt-3 text-sm font-medium text-white">安全入口</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">API Key 必须校验后才能进入</div>
            </div>
          </div>
        </div>

        <div class="glass-card w-full p-7 sm:p-8">
          <div class="mb-6 flex items-center gap-3">
            <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/30 to-cyan-500/20 text-2xl shadow-inner shadow-white/10">
              ⚡
            </div>
            <div>
              <h2 class="text-2xl font-semibold text-white">登录面板</h2>
              <p class="mt-1 text-sm text-slate-400">请输入 API Key 进入 AutoTeam</p>
            </div>
          </div>

          <div
            v-if="authError"
            class="mb-4 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300"
          >
            {{ authError }}
          </div>

          <div class="space-y-4">
            <div>
              <label class="mb-2 block text-sm font-medium text-slate-300">API Key</label>
              <input
                v-model.trim="inputKey"
                type="password"
                placeholder="输入 API Key"
                @keyup.enter="doLogin"
                class="input-dark"
              />
            </div>

            <button @click="doLogin" :disabled="!inputKey || authLoading" class="btn-primary w-full">
              {{ authLoading ? '验证中...' : '登录' }}
            </button>
          </div>

          <div class="mt-5 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs leading-6 text-slate-400">
            如果你是首次部署，启动后只需要先配置 API Key。CloudMail、CPA / Sub2API、代理等运行项可以在登录后进入配置面板继续设置。
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 主面板 -->
  <div v-else class="relative md:flex">
    <div class="pointer-events-none absolute inset-0 overflow-hidden">
      <div class="absolute left-[10%] top-0 h-72 w-72 rounded-full bg-blue-500/8 blur-3xl"></div>
      <div class="absolute bottom-0 right-[8%] h-80 w-80 rounded-full bg-cyan-500/8 blur-3xl"></div>
    </div>

    <!-- 侧边栏 -->
    <Sidebar :active="visiblePage" :loading="loading"
      @navigate="navigateTo" @refresh="refresh({ forceStatus: visiblePage === 'dashboard' })" />

    <!-- 主内容区 -->
    <div class="relative min-w-0 flex-1 overflow-y-auto pb-20 md:pb-8">
      <div class="mx-auto w-full max-w-[1500px] px-4 py-4 md:px-8 md:py-8">
        <header class="mb-5 rounded-2xl border border-white/10 bg-slate-950/55 px-4 py-3 backdrop-blur md:px-5">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div class="text-xs uppercase text-slate-500">AutoTeam</div>
              <h1 class="mt-1 text-xl font-semibold text-white">{{ pageTitle }}</h1>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button
                class="btn-danger min-h-10 gap-2 rounded-xl px-4"
                :disabled="stopAllLoading"
                title="强制停止当前全部工作"
                @click="forceStopAll"
              >
                <span aria-hidden="true" class="h-2.5 w-2.5 rounded-sm bg-current"></span>
                <span>{{ stopAllLoading ? '停止中...' : '停止全部工作' }}</span>
              </button>
              <button
                v-if="authRequired"
                class="btn-secondary min-h-10 gap-2 rounded-xl px-4"
                title="登出当前面板"
                @click="doLogout"
              >
                <span aria-hidden="true" class="text-base">🚪</span>
                <span>登出</span>
              </button>
            </div>
          </div>
          <div
            v-if="stopAllNotice || stopAllError"
            class="mt-3 rounded-xl border px-3 py-2 text-xs"
            :class="stopAllError
              ? 'border-rose-500/30 bg-rose-950/50 text-rose-100'
              : 'border-emerald-500/30 bg-emerald-950/50 text-emerald-100'"
          >
            {{ stopAllError || stopAllNotice }}
          </div>
        </header>

        <!-- 任务执行中提示 -->
        <div
          v-if="busyTask"
          class="mb-5 flex items-center gap-3 rounded-2xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200 backdrop-blur"
        >
          <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-amber-300 border-t-transparent"></span>
          <span class="font-medium">
            {{ busyTask.command === 'admin-login'
              ? '管理员登录中...'
              : busyTask.command === 'main-codex-sync'
                ? '主号 Codex 同步中...'
                : `${busyTask.command} 执行中...` }}
          </span>
        </div>

      <!-- 页面内容 -->
        <Dashboard v-if="visiblePage === 'dashboard'"
          :status="status" :loading="loading" :running-task="busyTask" :admin-status="adminStatus" @refresh="refresh" />

        <ConfigPage
          v-else-if="visiblePage === 'config'"
          :admin-status="adminStatus"
          :codex-status="codexStatus"
          @refresh="refresh"
          @admin-progress="onAdminProgress"
        />

        <TeamMembers v-else-if="visiblePage === 'team'" />

        <PoolPage v-else-if="visiblePage === 'pool'"
          :running-task="busyTask" :admin-status="adminStatus"
          @task-started="onTaskStarted" @refresh="refresh" />

        <SyncPage v-else-if="visiblePage === 'sync'"
          :running-task="busyTask" :admin-status="adminStatus"
          @task-started="onTaskStarted" @refresh="refresh" />

        <OAuthPage v-else-if="visiblePage === 'oauth'"
          :manual-account-status="manualAccountStatus"
          :running-task="busyTask"
          @refresh="refresh"
          @progress="onAdminProgress" />

        <AccountManagement v-else-if="visiblePage === 'accounts'"
          :loading="loading" @refresh="refresh" />

        <TaskHistoryPage v-else-if="visiblePage === 'tasks'"
          :tasks="tasks" />

        <LogViewer v-else-if="visiblePage === 'logs'" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, ref, onMounted, onUnmounted, watch } from 'vue'
import { api, setApiKey, clearApiKey } from './api.js'
import Sidebar from './components/Sidebar.vue'
import AccountManagement from './components/AccountManagement.vue'

const SetupPage = defineAsyncComponent(() => import('./components/SetupPage.vue'))
const Dashboard = defineAsyncComponent(() => import('./components/Dashboard.vue'))
const ConfigPage = defineAsyncComponent(() => import('./components/ConfigPage.vue'))
const TeamMembers = defineAsyncComponent(() => import('./components/TeamMembers.vue'))
const PoolPage = defineAsyncComponent(() => import('./components/PoolPage.vue'))
const SyncPage = defineAsyncComponent(() => import('./components/SyncPage.vue'))
const TaskHistoryPage = defineAsyncComponent(() => import('./components/TaskHistoryPage.vue'))
const LogViewer = defineAsyncComponent(() => import('./components/LogViewer.vue'))
const OAuthPage = defineAsyncComponent(() => import('./components/OAuthPage.vue'))

const needSetup = ref(false)
const authenticated = ref(false)
const authRequired = ref(false)
const authLoading = ref(false)
const authError = ref('')
const inputKey = ref('')
const currentPage = ref('dashboard')

const status = ref(null)
const adminStatus = ref(null)
const codexStatus = ref(null)
const manualAccountStatus = ref(null)
const tasks = ref([])
const loading = ref(false)
const runningTask = ref(null)
const stopAllLoading = ref(false)
const stopAllNotice = ref('')
const stopAllError = ref('')

const pageTitles = {
  dashboard: '仪表盘',
  config: '配置面板',
  team: 'Team 成员',
  pool: '账号池操作',
  sync: '同步中心',
  oauth: 'OAuth 登录',
  accounts: '账号工作台',
  tasks: '任务历史',
  logs: '日志',
}

const visiblePage = computed(() => currentPage.value === 'account-clean' ? 'accounts' : currentPage.value)
const pageTitle = computed(() => pageTitles[visiblePage.value] || 'AutoTeam')
const busyTask = computed(() => {
  if (adminStatus.value?.login_in_progress) {
    return { command: 'admin-login' }
  }
  if (codexStatus.value?.in_progress) {
    return { command: 'main-codex-sync' }
  }
  return runningTask.value
})

let pollTimer = null
let refreshSeq = 0

async function checkAuth() {
  try {
    const result = await api.checkAuth()
    authenticated.value = result.authenticated
    authRequired.value = result.auth_required
    return result.authenticated
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      authRequired.value = true
      return false
    }
    authenticated.value = true
    authRequired.value = false
    return true
  }
}

async function doLogin() {
  authError.value = ''
  authLoading.value = true
  try {
    setApiKey(inputKey.value)
    const ok = await checkAuth()
    if (!ok) {
      clearApiKey()
      authError.value = 'API Key 无效'
    } else {
      inputKey.value = ''
      refresh({ forceStatus: true })
      startPolling(600000)
    }
  } catch (e) {
    clearApiKey()
    authError.value = e.message
  } finally {
    authLoading.value = false
  }
}

function doLogout() {
  clearApiKey()
  authenticated.value = false
  stopPolling()
}

function needsStatusRefresh({ forceStatus = false } = {}) {
  return forceStatus || visiblePage.value === 'dashboard'
}

async function refresh(options = {}) {
  const seq = ++refreshSeq
  loading.value = true
  try {
    const requests = [
      api.getTasks(),
      api.getAdminStatus(),
      api.getMainCodexStatus(),
      api.getManualAccountStatus(),
    ]
    if (needsStatusRefresh(options)) {
      requests.unshift(api.getStatus({ realtimeQuota: !!options.realtimeQuota }))
    }

    const results = await Promise.all(requests)
    if (seq !== refreshSeq) return

    let offset = 0
    if (needsStatusRefresh(options)) {
      status.value = results[0]
      offset = 1
    }
    const [t, admin, codex, manualAccount] = results.slice(offset)
    tasks.value = t
    adminStatus.value = admin
    codexStatus.value = codex
    manualAccountStatus.value = manualAccount
    runningTask.value = t.find(t => t.status === 'running' || t.status === 'pending') || null
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      return
    }
    console.error('刷新失败:', e)
  } finally {
    if (seq === refreshSeq) {
      loading.value = false
    }
  }
}

function onTaskStarted() {
  startPolling(10000)
  refresh({ forceStatus: visiblePage.value === 'dashboard' })
}

function onAdminProgress() {
  startPolling(10000)
  refresh({ forceStatus: visiblePage.value === 'dashboard' })
}

function navigateTo(page) {
  const nextPage = page === 'account-clean' ? 'accounts' : page
  if (currentPage.value === nextPage) return
  currentPage.value = nextPage
}

async function forceStopAll() {
  if (stopAllLoading.value) return
  stopAllLoading.value = true
  stopAllNotice.value = ''
  stopAllError.value = ''
  try {
    const result = await api.stopAllTasks()
    const taskCount = result.stopped_tasks?.length || 0
    const flowCount = result.stopped_flows?.length || 0
    stopAllNotice.value = taskCount || flowCount
      ? `已请求停止 ${taskCount} 个任务、${flowCount} 个流程`
      : '当前没有需要停止的工作'
    await refresh({ forceStatus: visiblePage.value === 'dashboard' })
    startPolling(10000)
  } catch (e) {
    stopAllError.value = e.message || '停止失败'
  } finally {
    stopAllLoading.value = false
  }
}

function startPolling(interval = 600000) {
  stopPolling()
  pollTimer = setInterval(async () => {
    await refresh()
    if (!busyTask.value && interval < 600000) {
      startPolling(600000)
    }
  }, interval)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function checkSetup() {
  try {
    const result = await api.getSetupStatus()
    return result.configured
  } catch {
    return true // 接口不存在说明是旧版本，跳过
  }
}

function onSetupDone() {
  needSetup.value = false
  checkAuth().then(ok => {
    if (ok) {
      refresh({ forceStatus: true })
      startPolling(600000)
    }
  })
}

onMounted(async () => {
  const setupOk = await checkSetup()
  if (!setupOk) {
    needSetup.value = true
    return
  }
  const ok = await checkAuth()
  if (ok) {
    refresh({ forceStatus: true })
    startPolling(600000)
  }
})

watch(currentPage, () => {
  if (currentPage.value === 'account-clean') {
    currentPage.value = 'accounts'
    return
  }
  if (authenticated.value) {
    refresh({ forceStatus: visiblePage.value === 'dashboard' })
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>
