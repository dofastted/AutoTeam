<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-white">Team 成员</h2>
        <p class="text-xs text-gray-500 mt-1">仅显示母号 ChatGPT Team 实际加入成员</p>
      </div>
      <button @click="fetchMembers({ refresh: true })" :disabled="loading"
        class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm rounded-lg border border-gray-700 transition disabled:opacity-50">
        {{ loading ? '验证中...' : '验证刷新' }}
      </button>
    </div>

    <div v-if="error" class="mb-4 px-4 py-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20">
      {{ error }}
    </div>

    <div v-if="message" class="mb-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
      {{ message }}
    </div>

    <div v-if="data?.cached" class="mb-4 px-4 py-3 rounded-lg text-sm bg-blue-500/10 text-blue-300 border border-blue-500/20">
      当前显示{{ data.local_snapshot ? '本地账号快照' : '本地缓存' }}
      <span v-if="data.cache_updated_at">，更新时间 {{ formatCacheTime(data.cache_updated_at) }}</span>
      <span v-if="data.refresh_error" class="block mt-1 text-amber-300">远端验证失败：{{ formatRefreshError(data.refresh_error) }}</span>
    </div>

    <div v-if="data" class="space-y-4">
      <!-- 统计 -->
      <div class="flex flex-wrap gap-3 text-sm">
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          实际成员: <span class="text-white font-medium">{{ membersOnly.length }}</span>
        </span>
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          待接受邀请: <span class="text-white font-medium">{{ invitesOnly.length }}</span>
        </span>
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          每页: <span class="text-white font-medium">{{ pageSize }}</span>
        </span>
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          第 {{ currentPage }} / {{ totalPages }} 页
        </span>
      </div>

      <!-- 成员表格 -->
      <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-gray-400 text-left border-b border-gray-800">
                <th class="px-4 py-3 font-medium w-12">#</th>
                <th class="px-4 py-3 font-medium">邮箱</th>
                <th class="px-4 py-3 font-medium w-40">角色</th>
                <th class="px-4 py-3 font-medium w-48">加入时间</th>
                <th class="px-4 py-3 font-medium w-32 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in pagedMembers" :key="memberKey(m)"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 transition">
                <td class="px-4 py-3 text-gray-500">{{ pageStart + i + 1 }}</td>
                <td class="px-4 py-3 font-mono text-xs text-gray-200">{{ m.email }}</td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded text-xs font-medium"
                    :class="{
                      'bg-purple-500/10 text-purple-400': m.role === 'account-owner',
                      'bg-blue-500/10 text-blue-400': m.role === 'account-admin',
                      'bg-gray-500/10 text-gray-300': m.role !== 'account-owner' && m.role !== 'account-admin',
                    }">
                    {{ m.role || 'member' }}
                  </span>
                </td>
                <td class="px-4 py-3 text-xs text-gray-400">{{ formatJoinedAt(m.joined_at) }}</td>
                <td class="px-4 py-3 text-right">
                  <button
                    v-if="canRemove(m)"
                    @click="removeMember(m)"
                    :disabled="actionId === memberKey(m)"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                    :class="actionId === memberKey(m)
                      ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                      : 'bg-amber-600/10 text-amber-400 border-amber-500/30 hover:bg-amber-600/20'"
                  >
                    {{ actionId === memberKey(m) && actionType === 'remove' ? '处理中...' : '移出' }}
                  </button>
                  <span v-else class="text-xs text-gray-600">-</span>
                </td>
              </tr>
              <tr v-if="!pagedMembers.length">
                <td colspan="5" class="px-4 py-12 text-center text-gray-500 text-sm">
                  暂无成员
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 翻页 -->
        <div v-if="totalPages > 1" class="px-4 py-3 border-t border-gray-800 flex items-center justify-between">
          <div class="text-xs text-gray-500">
            显示 {{ pageStart + 1 }} - {{ pageEnd }} / {{ membersOnly.length }}
          </div>
          <div class="flex items-center gap-2">
            <button @click="goToPage(1)" :disabled="currentPage === 1"
              class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
              首页
            </button>
            <button @click="goToPage(currentPage - 1)" :disabled="currentPage === 1"
              class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
              上一页
            </button>
            <span class="text-xs text-gray-400 px-2">{{ currentPage }} / {{ totalPages }}</span>
            <button @click="goToPage(currentPage + 1)" :disabled="currentPage >= totalPages"
              class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
              下一页
            </button>
            <button @click="goToPage(totalPages)" :disabled="currentPage >= totalPages"
              class="px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed">
              末页
            </button>
          </div>
        </div>
      </div>

      <!-- 待接受邀请 -->
      <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <div>
            <div class="text-sm font-medium text-gray-200">待接受邀请</div>
            <div class="text-xs text-gray-500 mt-0.5">可取消误发或过期的邀请</div>
          </div>
          <div class="text-sm text-gray-400">
            共 <span class="text-white font-medium">{{ invitesOnly.length }}</span> 个邀请
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-gray-400 text-left border-b border-gray-800">
                <th class="px-4 py-3 font-medium w-12">#</th>
                <th class="px-4 py-3 font-medium">邮箱</th>
                <th class="px-4 py-3 font-medium w-40">角色</th>
                <th class="px-4 py-3 font-medium w-48">邀请时间</th>
                <th class="px-4 py-3 font-medium w-32 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in invitesOnly" :key="memberKey(m)"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 transition">
                <td class="px-4 py-3 text-gray-500">{{ i + 1 }}</td>
                <td class="px-4 py-3 font-mono text-xs text-gray-200">{{ m.email }}</td>
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded text-xs font-medium bg-amber-500/10 text-amber-300">
                    {{ m.role || 'invite' }}
                  </span>
                </td>
                <td class="px-4 py-3 text-xs text-gray-400">{{ formatJoinedAt(m.joined_at) }}</td>
                <td class="px-4 py-3 text-right">
                  <button
                    v-if="canRemove(m)"
                    @click="removeMember(m)"
                    :disabled="actionId === memberKey(m)"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                    :class="actionId === memberKey(m)
                      ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                      : 'bg-amber-600/10 text-amber-400 border-amber-500/30 hover:bg-amber-600/20'"
                  >
                    {{ actionId === memberKey(m) && actionType === 'remove' ? '处理中...' : '取消邀请' }}
                  </button>
                  <span v-else class="text-xs text-gray-600">-</span>
                </td>
              </tr>
              <tr v-if="!invitesOnly.length">
                <td colspan="5" class="px-4 py-10 text-center text-gray-500 text-sm">
                  暂无待接受邀请
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="bg-gray-900 border border-gray-800 rounded-xl h-64 animate-pulse"></div>

    <!-- Empty -->
    <div v-else class="text-center text-gray-500 py-12">
      点击「刷新」加载 Team 成员列表
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api.js'

const data = ref(null)
const loading = ref(false)
const error = ref('')
const message = ref('')
const messageClass = ref('')
const actionId = ref('')
const actionType = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

const CACHE_KEY = 'autoteam_team_members'

const membersOnly = computed(() => {
  if (!data.value || !Array.isArray(data.value.members)) return []
  return data.value.members.filter((m) => m.type === 'member')
})

const invitesOnly = computed(() => {
  if (!data.value || !Array.isArray(data.value.members)) return []
  return data.value.members.filter((m) => m.type === 'invite')
})

const totalPages = computed(() => Math.max(1, Math.ceil(membersOnly.value.length / pageSize.value)))
const pageStart = computed(() => (currentPage.value - 1) * pageSize.value)
const pageEnd = computed(() => Math.min(membersOnly.value.length, pageStart.value + pageSize.value))
const pagedMembers = computed(() => membersOnly.value.slice(pageStart.value, pageEnd.value))

watch(membersOnly, () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
  if (currentPage.value < 1) currentPage.value = 1
})

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (raw) {
      const cached = JSON.parse(raw)
      if (cached.time && Date.now() - cached.time < 600000) {
        return cached.data
      }
    }
  } catch {}
  return null
}

function saveCache(d) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ data: d, time: Date.now() }))
  } catch {}
}

function memberKey(member) {
  return `${member.type || 'member'}:${member.user_id || ''}:${member.email}`
}

function clearTeamCache() {
  try {
    localStorage.removeItem(CACHE_KEY)
  } catch {}
}

async function fetchMembers({ refresh = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getTeamMembers({ refresh })
    saveCache(data.value)
    if (currentPage.value > totalPages.value) currentPage.value = 1
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function goToPage(p) {
  if (p < 1 || p > totalPages.value) return
  currentPage.value = p
}

function formatCacheTime(ts) {
  const d = new Date(Number(ts) * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatJoinedAt(value) {
  if (!value) return '-'
  let d
  if (typeof value === 'number') {
    // 秒/毫秒
    d = new Date(value < 1e12 ? value * 1000 : value)
  } else if (typeof value === 'string') {
    // ISO 或者数字串
    if (/^\d+$/.test(value)) {
      const num = Number(value)
      d = new Date(num < 1e12 ? num * 1000 : num)
    } else {
      d = new Date(value)
    }
  } else {
    return '-'
  }
  if (Number.isNaN(d.getTime())) return '-'
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

function formatRefreshError(value) {
  if (typeof value === 'string') return value
  return value?.message || JSON.stringify(value)
}

function isOwner(member) {
  return member.role === 'account-owner' || member.is_main_account
}

function canRemove(member) {
  if (isOwner(member)) return false
  return true
}

function showMessage(text, kind = 'success') {
  message.value = text
  messageClass.value = kind === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  setTimeout(() => { message.value = '' }, 8000)
}

async function removeMember(member) {
  const isInvite = member.type === 'invite'
  const actionLabel = isInvite ? '取消邀请' : '移出 Team'
  const ok = window.confirm(`确认${actionLabel} ${member.email}？`)
  if (!ok) return

  actionId.value = memberKey(member)
  actionType.value = 'remove'
  error.value = ''
  try {
    const result = await api.removeTeamMember({
      email: member.email,
      user_id: member.user_id,
      type: member.type || 'member',
    })
    showMessage(result.message || `${actionLabel}完成: ${member.email}`)
    clearTeamCache()
    await fetchMembers({ refresh: true })
  } catch (e) {
    error.value = e.message
  } finally {
    actionId.value = ''
    actionType.value = ''
  }
}

onMounted(() => {
  const cached = loadCache()
  if (cached) {
    data.value = cached
  } else {
    fetchMembers({ refresh: false })
  }
})
</script>
