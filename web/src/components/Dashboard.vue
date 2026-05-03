<template>
  <div class="space-y-8">
    <!-- 账号状态 -->
    <section>
      <h2 class="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
        <span class="w-1 h-4 bg-blue-500 rounded"></span>
        账号状态
      </h2>
      <div v-if="status" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <div v-for="card in statusCards" :key="card.label"
          class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">{{ card.label }}</div>
          <div class="text-3xl font-bold mt-1" :class="card.color">{{ card.value }}</div>
        </div>
      </div>
      <div v-else-if="loading" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <div v-for="i in 5" :key="i" class="bg-gray-900 border border-gray-800 rounded-xl p-4 h-20 animate-pulse"></div>
      </div>
    </section>

    <!-- Team 成员 -->
    <section>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-medium text-gray-400 flex items-center gap-2">
          <span class="w-1 h-4 bg-emerald-500 rounded"></span>
          Team 成员
        </h2>
        <button @click="loadTeam(true)" :disabled="teamLoading"
          class="px-3 py-1 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-400 hover:text-white">
          {{ teamLoading ? '刷新中...' : '刷新' }}
        </button>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">实际成员</div>
          <div class="text-3xl font-bold mt-1 text-emerald-400">{{ teamStats.members }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">待接受邀请</div>
          <div class="text-3xl font-bold mt-1 text-amber-400">{{ teamStats.invites }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">合计</div>
          <div class="text-3xl font-bold mt-1 text-white">{{ teamStats.total }}</div>
        </div>
      </div>
      <div v-if="teamError" class="mt-3 px-3 py-2 rounded-lg text-xs bg-red-500/10 text-red-400 border border-red-500/20">
        {{ teamError }}
      </div>
    </section>

    <!-- 认证文件 -->
    <section>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-medium text-gray-400 flex items-center gap-2">
          <span class="w-1 h-4 bg-cyan-500 rounded"></span>
          认证文件 (auths/)
        </h2>
        <button @click="loadAuthsStats()" :disabled="authsLoading"
          class="px-3 py-1 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-400 hover:text-white">
          {{ authsLoading ? '刷新中...' : '刷新' }}
        </button>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">OAuth 文件</div>
          <div class="text-3xl font-bold mt-1 text-blue-400">{{ authsStats ? authsStats.oauth_files : '-' }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">Session 文件</div>
          <div class="text-3xl font-bold mt-1 text-purple-400">{{ authsStats ? authsStats.session_files : '-' }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">已售（账号）</div>
          <div class="text-3xl font-bold mt-1 text-cyan-300">{{ authsStats ? authsStats.accounts_sold : '-' }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">可交易（账号）</div>
          <div class="text-3xl font-bold mt-1 text-green-400">{{ authsStats ? authsStats.accounts_tradable : '-' }}</div>
        </div>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">不可用（账号）</div>
          <div class="text-3xl font-bold mt-1 text-red-400">{{ authsStats ? authsStats.accounts_unusable : '-' }}</div>
        </div>
      </div>
      <div class="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div class="bg-gray-900/60 border border-gray-800 rounded-xl p-3">
          <div class="text-xs text-gray-500">活跃（账号）</div>
          <div class="text-xl font-semibold mt-0.5 text-green-400">{{ authsStats ? authsStats.accounts_active : '-' }}</div>
        </div>
        <div class="bg-gray-900/60 border border-gray-800 rounded-xl p-3">
          <div class="text-xs text-gray-500">归档（账号）</div>
          <div class="text-xl font-semibold mt-0.5 text-gray-400">{{ authsStats ? authsStats.accounts_archive : '-' }}</div>
        </div>
        <div class="bg-gray-900/60 border border-gray-800 rounded-xl p-3">
          <div class="text-xs text-gray-500">唯一邮箱</div>
          <div class="text-xl font-semibold mt-0.5 text-gray-200">{{ authsStats ? authsStats.unique_emails : '-' }}</div>
        </div>
        <div class="bg-gray-900/60 border border-gray-800 rounded-xl p-3">
          <div class="text-xs text-gray-500">文件总数</div>
          <div class="text-xl font-semibold mt-0.5 text-gray-200">{{ authsStats ? authsStats.total_files : '-' }}</div>
        </div>
      </div>
      <div v-if="authsError" class="mt-3 px-3 py-2 rounded-lg text-xs bg-red-500/10 text-red-400 border border-red-500/20">
        {{ authsError }}
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  status: Object,
  loading: Boolean,
  runningTask: Object,
  adminStatus: {
    type: Object,
    default: null,
  },
})

const teamData = ref(null)
const teamLoading = ref(false)
const teamError = ref('')
const authsStats = ref(null)
const authsLoading = ref(false)
const authsError = ref('')

const statusCards = computed(() => {
  if (!props.status) return []
  const s = props.status.summary || {}
  return [
    { label: '活跃', value: s.active ?? 0, color: 'text-green-400' },
    { label: '待命', value: s.standby ?? 0, color: 'text-yellow-400' },
    { label: '额度用完', value: s.exhausted ?? 0, color: 'text-red-400' },
    { label: '已售', value: s.sold ?? 0, color: 'text-cyan-300' },
    { label: '总计', value: s.total ?? 0, color: 'text-white' },
  ]
})

// _format_team_payload 把 invites 也塞在 members 数组里(用 type 区分)
// total/invites 是真实成员/邀请的整数计数
const teamStats = computed(() => {
  if (!teamData.value) return { members: '-', invites: '-', total: '-' }
  const t = teamData.value
  let memberCount, inviteCount
  if (typeof t.total === 'number' && typeof t.invites === 'number') {
    memberCount = t.total
    inviteCount = t.invites
  } else {
    // 兜底:从 members 数组按 type 过滤
    const arr = Array.isArray(t.members) ? t.members : []
    memberCount = arr.filter((m) => m.type === 'member').length
    inviteCount = arr.filter((m) => m.type === 'invite').length
  }
  return {
    members: memberCount,
    invites: inviteCount,
    total: memberCount + inviteCount,
  }
})

async function loadTeam(refresh = false) {
  teamLoading.value = true
  teamError.value = ''
  try {
    teamData.value = await api.getTeamMembers({ refresh })
  } catch (e) {
    teamError.value = e.message
  } finally {
    teamLoading.value = false
  }
}

async function loadAuthsStats() {
  authsLoading.value = true
  authsError.value = ''
  try {
    authsStats.value = await api.getAuthsStats()
  } catch (e) {
    authsError.value = e.message
  } finally {
    authsLoading.value = false
  }
}

onMounted(() => {
  loadTeam(false)
  loadAuthsStats()
})
</script>
