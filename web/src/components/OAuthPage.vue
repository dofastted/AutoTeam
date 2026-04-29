<template>
  <div class="mt-6 space-y-6">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex flex-col gap-3 mb-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 class="text-lg font-semibold text-white">CPA 凭证检查</h2>
          <p class="text-sm text-gray-400 mt-1">
            对比 active 席位账号和 CPA 认证文件。缺少凭证时，可直接为该账号完成 Codex 认证并上传到 CPA。
          </p>
        </div>
        <button
          @click="refreshCpaStatus"
          :disabled="cpaLoading"
          class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-300"
        >
          {{ cpaLoading ? '刷新中...' : '刷新' }}
        </button>
      </div>

      <div v-if="cpaError" class="mb-4 px-4 py-3 rounded-lg text-sm border bg-amber-500/10 text-amber-300 border-amber-500/20">
        {{ cpaError }}
      </div>

      <div class="grid grid-cols-3 gap-3 mb-4">
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">active 席位</div>
          <div class="mt-1 text-xl font-semibold text-white">{{ cpaSummary.active }}</div>
        </div>
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">CPA 已有</div>
          <div class="mt-1 text-xl font-semibold text-emerald-300">{{ cpaSummary.ready }}</div>
        </div>
        <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
          <div class="text-xs text-gray-500">待处理</div>
          <div class="mt-1 text-xl font-semibold text-amber-300">{{ cpaSummary.missing }}</div>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-gray-400 text-left border-b border-gray-800">
              <th class="px-4 py-3 font-medium">邮箱</th>
              <th class="px-4 py-3 font-medium">本地凭证</th>
              <th class="px-4 py-3 font-medium">CPA 凭证</th>
              <th class="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!cpaLoading && cpaRows.length === 0">
              <td colspan="4" class="px-4 py-6 text-center text-gray-500">暂无 active 席位账号</td>
            </tr>
            <tr
              v-for="row in cpaRows"
              :key="row.email"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 transition"
            >
              <td class="px-4 py-3 font-mono text-xs text-gray-200">{{ row.email }}</td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium border"
                  :class="row.hasLocalAuth
                    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/20'"
                >
                  {{ row.hasLocalAuth ? '已有' : '缺少' }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span
                  class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium border"
                  :class="row.hasCpaAuth
                    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/20'"
                >
                  {{ row.hasCpaAuth ? '已有' : '缺少' }}
                </span>
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  @click="startCpaAuth(row.email)"
                  :disabled="cpaActionDisabled(row)"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                  :class="cpaActionDisabled(row)
                    ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                    : 'bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20'"
                >
                  {{ cpaActionEmail === row.email ? '提交中...' : row.hasCpaAuth ? '重新上传' : '认证并上传' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">OAuth 登录</h2>
          <p class="text-sm text-gray-400 mt-1">
            参考 CLIProxyAPI 的手动 OAuth 思路：系统先生成认证链接，你在浏览器中手动完成登录，最后把回调 URL 粘贴回来完成认证。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="manualAccountBusy
            ? 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'"
        >
          {{ manualAccountBusy ? '进行中' : '空闲' }}
        </span>
      </div>

      <div v-if="message" class="mb-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div
        v-if="manualAccountStatus?.status === 'completed' && manualAccountStatus?.account"
        class="mb-4 px-4 py-3 rounded-lg text-sm border bg-green-500/10 text-green-400 border-green-500/20"
      >
        {{ manualAccountStatus.message || `已添加账号 ${manualAccountStatus.account.email}` }}
      </div>

      <div
        v-else-if="manualAccountStatus?.status === 'error' && manualAccountStatus?.error"
        class="mb-4 px-4 py-3 rounded-lg text-sm border bg-red-500/10 text-red-400 border-red-500/20"
      >
        {{ manualAccountStatus.error }}
      </div>

      <div v-if="!manualAccountBusy" class="flex flex-wrap gap-3">
        <button
          @click="startManualAccount"
          :disabled="manualSubmitting"
          class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ manualSubmitting ? '生成中...' : '生成 OAuth 链接' }}
        </button>
      </div>

      <div v-else class="space-y-4">
        <div class="text-sm text-gray-300">
          已生成 OAuth 链接。若当前机器可访问 <span class="font-mono">localhost:1455</span>，系统会自动接收回调；否则请手动粘贴最终回调 URL。
        </div>

        <div
          class="px-4 py-3 rounded-lg text-sm border"
          :class="manualAccountStatus?.auto_callback_available
            ? 'bg-blue-500/10 text-blue-300 border-blue-500/20'
            : 'bg-amber-500/10 text-amber-300 border-amber-500/20'"
        >
          {{
            manualAccountStatus?.auto_callback_available
              ? '本地自动回调服务已启动：OpenAI 跳回 localhost:1455 后会自动完成认证。'
              : `本地自动回调不可用：${manualAccountStatus?.auto_callback_error || '请改用手动粘贴回调 URL'}`
          }}
        </div>

        <div class="space-y-2">
          <div class="text-xs text-gray-500">OAuth 链接</div>
          <div class="p-3 bg-gray-800 border border-gray-700 rounded-lg text-xs font-mono break-all text-gray-200">
            {{ manualAccountStatus?.auth_url }}
          </div>
        </div>

        <div class="flex flex-wrap gap-3">
          <a
            :href="manualAccountStatus?.auth_url"
            target="_blank"
            rel="noopener noreferrer"
            class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition"
          >
            打开 OAuth 链接
          </a>
        </div>

        <div
          v-if="manualAccountStatus?.callback_received"
          class="text-xs text-emerald-300"
        >
          已收到{{ manualAccountStatus?.callback_source === 'auto' ? '自动' : '手动' }}回调，刷新轮询中…
        </div>

        <div class="space-y-3">
          <input
            v-model.trim="manualCallbackUrl"
            type="text"
            placeholder="粘贴回调 URL，例如 http://localhost:1455/auth/callback?code=...&state=..."
            :disabled="manualSubmitting"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <button
            @click="submitManualCallback"
            :disabled="manualSubmitting || !manualCallbackUrl"
            class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition disabled:opacity-50"
          >
            {{ manualSubmitting ? '提交中...' : '提交回调 URL' }}
          </button>
        </div>

        <div v-if="manualSubmitting && manualSubmittingHint" class="text-xs text-emerald-300">
          {{ manualSubmittingHint }}
        </div>

        <div class="flex justify-end">
          <button
            @click="cancelManualAccount"
            :disabled="manualSubmitting"
            class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            取消 OAuth 登录
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  manualAccountStatus: {
    type: Object,
    default: null,
  },
  runningTask: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh', 'progress'])

const manualCallbackUrl = ref('')
const manualSubmitting = ref(false)
const manualSubmittingHint = ref('')
const message = ref('')
const messageClass = ref('')
const cpaAccounts = ref([])
const cpaFiles = ref([])
const cpaLoading = ref(false)
const cpaError = ref('')
const cpaActionEmail = ref('')

const manualAccountBusy = computed(() => !!props.manualAccountStatus?.in_progress)
const cpaEmailSet = computed(() => {
  return new Set(
    cpaFiles.value
      .map((file) => String(file.email || '').trim().toLowerCase())
      .filter(Boolean),
  )
})
const cpaRows = computed(() => {
  return cpaAccounts.value
    .filter((acc) => acc.status === 'active' && !acc.is_main_account)
    .map((acc) => {
      const email = String(acc.email || '').trim().toLowerCase()
      return {
        email,
        hasLocalAuth: !!acc.auth_file,
        hasCpaAuth: cpaEmailSet.value.has(email),
      }
    })
    .sort((a, b) => {
      if (a.hasCpaAuth !== b.hasCpaAuth) return a.hasCpaAuth ? 1 : -1
      if (a.hasLocalAuth !== b.hasLocalAuth) return a.hasLocalAuth ? 1 : -1
      return a.email.localeCompare(b.email)
    })
})
const cpaSummary = computed(() => {
  const active = cpaRows.value.length
  const ready = cpaRows.value.filter((row) => row.hasCpaAuth).length
  return {
    active,
    ready,
    missing: active - ready,
  }
})

watch(
  () => props.manualAccountStatus,
  (next) => {
    if (!next?.in_progress) {
      manualCallbackUrl.value = ''
      manualSubmittingHint.value = ''
    }
  },
  { immediate: true },
)

watch(
  () => props.runningTask,
  (next, prev) => {
    if (prev && !next) {
      refreshCpaStatus()
    }
  },
)

onMounted(() => {
  refreshCpaStatus()
})

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

async function startManualAccount() {
  manualSubmitting.value = true
  manualSubmittingHint.value = '正在生成 OAuth 链接...'
  try {
    const result = await api.startManualAccount()
    setMessage(result.auth_url ? 'OAuth 链接已生成，请完成登录后粘贴回调 URL' : '已开始 OAuth 登录流程')
    emit('progress')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
    manualSubmittingHint.value = ''
  }
}

async function submitManualCallback() {
  manualSubmitting.value = true
  manualSubmittingHint.value = '正在提交回调 URL 并交换 token...'
  try {
    const result = await api.submitManualAccountCallback(manualCallbackUrl.value)
    setMessage(result.status === 'completed' ? (result.message || '账号已添加') : '回调 URL 已提交')
    emit('progress')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
    manualSubmittingHint.value = ''
  }
}

async function cancelManualAccount() {
  manualSubmitting.value = true
  try {
    await api.cancelManualAccount()
    manualCallbackUrl.value = ''
    setMessage('OAuth 登录流程已取消')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
  }
}

async function refreshCpaStatus() {
  cpaLoading.value = true
  cpaError.value = ''
  try {
    cpaAccounts.value = await api.getAccounts()
    try {
      cpaFiles.value = await api.getCpaFiles()
    } catch (e) {
      cpaFiles.value = []
      cpaError.value = e.message
    }
  } catch (e) {
    cpaError.value = e.message
  } finally {
    cpaLoading.value = false
  }
}

function cpaActionDisabled(row) {
  return !!props.runningTask || cpaActionEmail.value === row.email || cpaLoading.value
}

async function startCpaAuth(email) {
  if (cpaActionDisabled({ email })) return
  cpaActionEmail.value = email
  try {
    const result = await api.startAccountCpaAuth(email)
    setMessage(`已提交 ${email} 的 CPA 认证任务: ${result.task_id}`)
    emit('progress')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    cpaActionEmail.value = ''
  }
}
</script>
