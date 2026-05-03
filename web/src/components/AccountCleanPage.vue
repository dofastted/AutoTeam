<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between gap-4">
      <div>
        <h2 class="text-xl font-bold text-white mb-2">账号清理</h2>
        <p class="text-sm text-gray-400">
          先扫描 `accounts.json`，确认重复邮箱、缺密码、错误凭证引用，再决定是否应用清理。
        </p>
      </div>
      <button
        v-if="hasDryRun"
        @click="resetState"
        :disabled="busy"
        class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-300"
      >
        重新开始
      </button>
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="flex flex-1 items-center gap-2 md:gap-4 overflow-x-auto">
          <div
            v-for="item in stepItems"
            :key="item.value"
            class="flex items-center gap-2 min-w-fit"
          >
            <button
              type="button"
              :disabled="!canJumpToStep(item.value) || busy"
              class="flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50"
              :class="stepPillClass(item.value)"
              @click="jumpToStep(item.value)"
            >
              <span class="text-base">{{ stepIcon(item.value) }}</span>
              <span>{{ item.label }}</span>
            </button>
            <div
              v-if="item.value !== stepItems[stepItems.length - 1].value"
              class="h-px w-8 bg-gray-700 md:w-12"
            ></div>
          </div>
        </div>
        <div class="text-xs text-gray-500">
          当前步骤：{{ currentStepLabel }}
        </div>
      </div>
    </div>

    <div v-if="error" class="bg-red-500/10 border border-red-500/30 text-red-200 p-3 rounded">
      {{ error }}
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-white">第 1 步：扫描</h3>
          <p class="text-sm text-gray-400 mt-1">
            扫描不会写入文件，只返回风险报告和 CSV。
          </p>
        </div>
        <div class="flex flex-wrap gap-3">
          <button
            @click="runDryRun"
            :disabled="busy"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="busy
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-cyan-600 text-white border-cyan-500 hover:bg-cyan-500'"
          >
            {{ busy && activeAction === 'dry-run' ? '扫描中...' : '扫描账号' }}
          </button>
          <button
            v-if="hasDryRun"
            @click="jumpToStep(2)"
            :disabled="busy"
            class="px-4 py-2 rounded-lg text-sm font-medium border transition"
            :class="busy
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-gray-800 text-gray-200 border-gray-700 hover:bg-gray-700'"
          >
            查看预览
          </button>
        </div>
      </div>

      <div v-if="hasDryRun" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">总账号数</div>
          <div class="mt-1 text-2xl font-semibold text-white">{{ dryRunReport.total_accounts }}</div>
        </div>
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">重复邮箱组</div>
          <div class="mt-1 text-2xl font-semibold text-amber-300">{{ duplicateGroups.length }}</div>
        </div>
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">风险项总数</div>
          <div class="mt-1 text-2xl font-semibold text-rose-300">{{ totalIssues }}</div>
        </div>
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">CSV</div>
          <div class="mt-1 text-sm font-medium" :class="dryRunCsv ? 'text-emerald-300' : 'text-gray-500'">
            {{ dryRunCsv ? '已生成' : '未生成' }}
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="hasDryRun"
      class="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-5"
    >
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-white">第 2 步：预览风险</h3>
          <p class="text-sm text-gray-400 mt-1">
            先看重复组和异常分类，再决定是否应用清理。
          </p>
        </div>
        <div class="flex flex-wrap gap-3">
          <button
            @click="downloadCsv"
            :disabled="!dryRunCsv || busy"
            class="px-3 py-2 rounded-lg text-sm font-medium border transition"
            :class="!dryRunCsv || busy
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'"
          >
            下载 CSV
          </button>
          <button
            @click="showFullJson = !showFullJson"
            class="px-3 py-2 rounded-lg text-sm font-medium border transition bg-gray-800 text-gray-200 border-gray-700 hover:bg-gray-700"
          >
            {{ showFullJson ? '收起完整 JSON' : '查看完整 JSON' }}
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div
          v-for="card in summaryCards"
          :key="card.key"
          class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3"
        >
          <div class="text-xs text-gray-500">{{ card.label }}</div>
          <div class="mt-1 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
        </div>
      </div>

      <div class="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <div class="rounded-lg border border-gray-800 overflow-hidden">
          <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/50">
            <div class="text-sm font-medium text-white">重复邮箱组</div>
          </div>
          <div v-if="duplicateGroups.length === 0" class="px-4 py-6 text-sm text-gray-500">
            没有发现重复邮箱组。
          </div>
          <div v-else class="divide-y divide-gray-800/70">
            <div
              v-for="group in duplicateGroups"
              :key="`${group.email}-${group.count}`"
              class="px-4 py-3"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="font-mono text-sm text-gray-200 break-all">{{ group.email }}</div>
                <div class="text-xs text-amber-300">{{ group.count }} 条</div>
              </div>
              <div class="mt-2 text-xs text-gray-500 break-all">
                IDs: {{ formatIdList(group.ids) }}
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-lg border border-gray-800 overflow-hidden">
          <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/50">
            <div class="text-sm font-medium text-white">风险分类</div>
          </div>
          <div class="divide-y divide-gray-800/70">
            <div
              v-for="issue in issueSummaryRows"
              :key="issue.key"
              class="px-4 py-3 flex items-center justify-between gap-3"
            >
              <div>
                <div class="text-sm text-gray-200">{{ issue.label }}</div>
                <div class="text-xs text-gray-500">{{ issue.desc }}</div>
              </div>
              <div class="text-sm font-semibold" :class="issue.count > 0 ? 'text-rose-300' : 'text-emerald-300'">
                {{ issue.count }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="rounded-lg border border-gray-800 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/50 flex items-center justify-between gap-3">
          <div class="text-sm font-medium text-white">问题明细</div>
          <div class="text-xs text-gray-500">每类只展开前 5 条</div>
        </div>
        <div class="divide-y divide-gray-800/70">
          <div
            v-for="issue in issueDetailRows"
            :key="issue.key"
            class="px-4 py-4"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="text-sm font-medium text-gray-200">{{ issue.label }}</div>
              <div class="text-xs text-gray-500">{{ issue.count }} 条</div>
            </div>
            <div v-if="issue.items.length === 0" class="mt-2 text-sm text-gray-500">
              无
            </div>
            <div v-else class="mt-3 space-y-2">
              <div
                v-for="item in issue.items"
                :key="`${issue.key}-${item.email}-${item.detail}`"
                class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3"
              >
                <div class="font-mono text-xs text-gray-200 break-all">
                  {{ item.email || '-' }}
                </div>
                <div class="mt-1 text-xs text-gray-400 break-all">
                  {{ item.detail || '-' }}
                </div>
              </div>
              <div v-if="issue.count > issue.items.length" class="text-xs text-gray-500">
                还有 {{ issue.count - issue.items.length }} 条未展开，请查看完整 JSON 或下载 CSV。
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="showFullJson" class="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
        <pre class="text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap">{{ dryRunJson }}</pre>
      </div>
    </div>

    <div
      v-if="hasDryRun"
      class="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-5"
    >
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-white">第 3 步：应用</h3>
          <p class="text-sm text-gray-400 mt-1">
            应用前会自动备份 `accounts.json`，应用后会再次扫描验证结果。
          </p>
        </div>
        <button
          @click="runApply"
          :disabled="busy || !hasDryRun"
          class="px-4 py-2 rounded-lg text-sm font-medium border transition"
          :class="busy || !hasDryRun
            ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
            : 'bg-rose-600/10 text-rose-200 border-rose-500/30 hover:bg-rose-600/20'"
        >
          {{ busy && activeAction === 'apply' ? '应用中...' : '应用清理（已确认）' }}
        </button>
      </div>

      <div v-if="applyResult" class="space-y-5">
        <div class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          清理已执行完成。
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="text-xs text-gray-500">备份路径</div>
            <div class="mt-1 text-sm font-mono text-cyan-300 break-all">{{ backupPathDisplay }}</div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="text-xs text-gray-500">迁移条数</div>
            <div class="mt-1 text-2xl font-semibold text-white">{{ reclassifySummary.schemaChanges }}</div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="text-xs text-gray-500">凭证修正</div>
            <div class="mt-1 text-2xl font-semibold text-amber-300">{{ reclassifySummary.credentialChanges }}</div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="text-xs text-gray-500">去重对数</div>
            <div class="mt-1 text-2xl font-semibold text-rose-300">{{ reclassifySummary.mergeCount }}</div>
          </div>
        </div>

        <div class="grid gap-5 xl:grid-cols-[1fr_1fr]">
          <div class="rounded-lg border border-gray-800 overflow-hidden">
            <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/50">
              <div class="text-sm font-medium text-white">分类结果</div>
            </div>
            <div class="divide-y divide-gray-800/70">
              <div
                v-for="item in categoryCountRows"
                :key="item.key"
                class="px-4 py-3 flex items-center justify-between gap-3"
              >
                <div class="text-sm text-gray-200">{{ item.key }}</div>
                <div class="text-sm font-semibold text-cyan-300">{{ item.value }}</div>
              </div>
              <div v-if="categoryCountRows.length === 0" class="px-4 py-6 text-sm text-gray-500">
                无分类统计。
              </div>
            </div>
          </div>

          <div class="rounded-lg border border-gray-800 overflow-hidden">
            <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/50">
              <div class="text-sm font-medium text-white">应用后复扫</div>
            </div>
            <div class="divide-y divide-gray-800/70">
              <div class="px-4 py-3 flex items-center justify-between gap-3">
                <div>
                  <div class="text-sm text-gray-200">重复邮箱组</div>
                  <div class="text-xs text-gray-500">应尽量收敛到 0</div>
                </div>
                <div class="text-lg font-semibold" :class="afterDuplicateGroups.length === 0 ? 'text-emerald-300' : 'text-amber-300'">
                  {{ afterDuplicateGroups.length }}
                </div>
              </div>
              <div
                v-for="issue in afterIssueSummaryRows"
                :key="issue.key"
                class="px-4 py-3 flex items-center justify-between gap-3"
              >
                <div class="text-sm text-gray-200">{{ issue.label }}</div>
                <div class="text-sm font-semibold" :class="issue.count > 0 ? 'text-amber-300' : 'text-emerald-300'">
                  {{ issue.count }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="reportAfter" class="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="text-sm font-medium text-white">应用后完整 JSON</div>
            <button
              @click="showAfterJson = !showAfterJson"
              class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition text-gray-300"
            >
              {{ showAfterJson ? '收起' : '展开' }}
            </button>
          </div>
          <pre
            v-if="showAfterJson"
            class="text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap"
          >{{ reportAfterJson }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  loading: Boolean,
})

const emit = defineEmits(['refresh'])

const ISSUE_META = [
  { key: 'duplicate_emails', label: '重复邮箱', desc: '同一邮箱出现多条账号记录' },
  { key: 'missing_password', label: '缺密码', desc: '已注册账号缺少 password' },
  { key: 'missing_rt_auth_file', label: '缺 RT 文件', desc: '没有可上传的 OAuth RT 凭证' },
  { key: 'session_used_as_auth_file', label: 'session 当作 auth_file', desc: 'auth_file 指到了 session 备份' },
  { key: 'sold_sync_enabled', label: 'sold 但 sync 未禁', desc: '已售账号仍允许同步' },
  { key: 'invalid_in_inventory', label: 'invalid 仍在库存', desc: '失效账号仍标成 inventory' },
  { key: 'cpa_success_not_inventory', label: 'CPA 成功但未标库存', desc: 'cpa_status=success 但 usage_status 不对' },
  { key: 'missing_credential_file', label: '凭证文件缺失', desc: '引用的认证文件不存在' },
]

const stepItems = [
  { value: 1, label: '扫描' },
  { value: 2, label: '预览' },
  { value: 3, label: '应用' },
]

const step = ref(1)
const localLoading = ref(false)
const activeAction = ref('')
const error = ref('')
const dryRunReport = ref(null)
const dryRunCsv = ref('')
const applyResult = ref(null)
const reportAfter = ref(null)
const backupPath = ref('')
const showFullJson = ref(false)
const showAfterJson = ref(false)

const busy = computed(() => props.loading || localLoading.value)
const hasDryRun = computed(() => !!dryRunReport.value)
const duplicateGroups = computed(() => dryRunReport.value?.duplicate_groups || [])
const afterDuplicateGroups = computed(() => reportAfter.value?.duplicate_groups || [])
const currentStepLabel = computed(() => stepItems.find((item) => item.value === step.value)?.label || '扫描')
const totalIssues = computed(() => {
  return ISSUE_META.reduce((sum, item) => sum + issueCount(dryRunReport.value, item.key), 0)
})
const dryRunJson = computed(() => JSON.stringify(dryRunReport.value || {}, null, 2))
const reportAfterJson = computed(() => JSON.stringify(reportAfter.value || {}, null, 2))
const backupPathDisplay = computed(() => backupPath.value || applyResult.value?.backup_path || '-')
const reclassifySummary = computed(() => {
  const reclassify = applyResult.value?.reclassify || {}
  return {
    schemaChanges: reclassify.schema_changes || 0,
    credentialChanges: reclassify.credential_changes || 0,
    mergeCount: reclassify.merge_count || 0,
  }
})

const summaryCards = computed(() => {
  if (!dryRunReport.value) return []
  return [
    { key: 'total_accounts', label: '总账号数', value: dryRunReport.value.total_accounts || 0, color: 'text-white' },
    { key: 'duplicate_groups', label: '重复邮箱组', value: duplicateGroups.value.length, color: 'text-amber-300' },
    { key: 'missing_password', label: '缺密码', value: issueCount(dryRunReport.value, 'missing_password'), color: 'text-rose-300' },
    { key: 'missing_rt_auth_file', label: '缺 RT 文件', value: issueCount(dryRunReport.value, 'missing_rt_auth_file'), color: 'text-rose-300' },
    { key: 'session_used_as_auth_file', label: 'session 当作 auth_file', value: issueCount(dryRunReport.value, 'session_used_as_auth_file'), color: 'text-amber-300' },
    { key: 'sold_sync_enabled', label: 'sold 但 sync 未禁', value: issueCount(dryRunReport.value, 'sold_sync_enabled'), color: 'text-amber-300' },
    { key: 'missing_credential_file', label: '凭证文件缺失', value: issueCount(dryRunReport.value, 'missing_credential_file'), color: 'text-rose-300' },
    { key: 'total_issues', label: '风险项总数', value: totalIssues.value, color: 'text-cyan-300' },
  ]
})

const issueSummaryRows = computed(() => {
  return ISSUE_META.map((item) => ({
    ...item,
    count: issueCount(dryRunReport.value, item.key),
  }))
})

const issueDetailRows = computed(() => {
  return ISSUE_META.map((item) => ({
    ...item,
    count: issueCount(dryRunReport.value, item.key),
    items: issueItems(dryRunReport.value, item.key).slice(0, 5),
  }))
})

const afterIssueSummaryRows = computed(() => {
  return ISSUE_META.map((item) => ({
    ...item,
    count: issueCount(reportAfter.value, item.key),
  }))
})

const categoryCountRows = computed(() => {
  const counts = applyResult.value?.reclassify?.category_counts || {}
  return Object.entries(counts)
    .map(([key, value]) => ({ key, value }))
    .sort((a, b) => String(a.key).localeCompare(String(b.key)))
})

function issueItems(report, key) {
  const issues = report?.issues
  if (!issues || typeof issues !== 'object') return []
  const items = issues[key]
  return Array.isArray(items) ? items : []
}

function issueCount(report, key) {
  const summary = report?.summary
  if (summary && typeof summary === 'object' && typeof summary[key] === 'number') {
    return summary[key]
  }
  return issueItems(report, key).length
}

function resetState() {
  step.value = 1
  error.value = ''
  dryRunReport.value = null
  dryRunCsv.value = ''
  applyResult.value = null
  reportAfter.value = null
  backupPath.value = ''
  showFullJson.value = false
  showAfterJson.value = false
}

function canJumpToStep(targetStep) {
  if (targetStep === 1) return true
  if (targetStep === 2) return hasDryRun.value
  if (targetStep === 3) return hasDryRun.value
  return false
}

function jumpToStep(targetStep) {
  if (!canJumpToStep(targetStep)) return
  step.value = targetStep
}

function stepIcon(targetStep) {
  if (step.value > targetStep) return '✅'
  if (step.value === targetStep) return targetStep === 3 && applyResult.value ? '✅' : '🟢'
  return '⏳'
}

function stepPillClass(targetStep) {
  if (step.value > targetStep || (targetStep === 3 && applyResult.value)) {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  }
  if (step.value === targetStep) {
    return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
  }
  return 'border-gray-700 bg-gray-800 text-gray-400'
}

async function runDryRun() {
  localLoading.value = true
  activeAction.value = 'dry-run'
  error.value = ''
  applyResult.value = null
  reportAfter.value = null
  backupPath.value = ''
  showAfterJson.value = false
  try {
    const data = await api.postAccountsCleanDryRun()
    dryRunReport.value = data.report
    dryRunCsv.value = data.csv || ''
    step.value = 2
  } catch (e) {
    error.value = e.message
  } finally {
    localLoading.value = false
    activeAction.value = ''
  }
}

async function runApply() {
  if (!hasDryRun.value) return
  const confirmed = window.confirm('是否确认应用清理？此操作会自动备份 accounts.json。')
  if (!confirmed) return

  localLoading.value = true
  activeAction.value = 'apply'
  error.value = ''
  try {
    const data = await api.postAccountsCleanApply()
    backupPath.value = data.backup_path || ''
    applyResult.value = data.result
    reportAfter.value = data.report_after
    step.value = 3
    emit('refresh')
  } catch (e) {
    error.value = e.message
  } finally {
    localLoading.value = false
    activeAction.value = ''
  }
}

function downloadCsv() {
  if (!dryRunCsv.value) return
  const blob = new Blob([dryRunCsv.value], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `account-clean-report-${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function formatIdList(ids) {
  if (!Array.isArray(ids) || ids.length === 0) return '-'
  return ids.map((id) => (id == null || id === '' ? '-' : String(id))).join(', ')
}
</script>
