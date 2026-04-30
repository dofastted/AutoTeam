<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-bold text-white">Team 成员</h2>
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
      <div class="flex gap-4 text-sm">
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">成员: <span class="text-white font-medium">{{ data.total }}</span></span>
        <span v-if="data.invites > 0" class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">待接受邀请: <span class="text-yellow-400 font-medium">{{ data.invites }}</span></span>
      </div>

      <!-- 成员表格 -->
      <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-gray-400 text-left border-b border-gray-800">
                <th class="px-4 py-3 font-medium">#</th>
                <th class="px-4 py-3 font-medium">邮箱</th>
                <th class="px-4 py-3 font-medium">角色</th>
                <th class="px-4 py-3 font-medium">类型</th>
                <th class="px-4 py-3 font-medium">账号状态</th>
                <th class="px-4 py-3 font-medium">认证</th>
                <th class="px-4 py-3 font-medium">来源</th>
                <th class="px-4 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(m, i) in data.members" :key="m.email + m.type"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 transition">
                <td class="px-4 py-3 text-gray-500">{{ i + 1 }}</td>
                <td class="px-4 py-3 font-mono text-xs">{{ m.email }}</td>
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
                <td class="px-4 py-3">
                  <span class="px-2 py-0.5 rounded text-xs font-medium"
                    :class="m.type === 'invite' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-green-500/10 text-green-400'">
                    {{ m.type === 'invite' ? '待接受' : '已加入' }}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <div v-if="m.is_local" class="flex flex-wrap items-center gap-2">
                    <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                      :class="statusClass(m.status)">
                      <span class="w-1.5 h-1.5 rounded-full" :class="dotClass(m.status)"></span>
                      {{ statusLabel(m.status) }}
                    </span>
                    <span v-if="m.sync_disabled"
                      class="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-300">
                      停止同步
                    </span>
                    <span v-if="m.has_cpa_archive_file"
                      class="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-700 text-gray-300">
                      已归档
                    </span>
                  </div>
                  <span v-else class="text-xs text-gray-500">-</span>
                </td>
                <td class="px-4 py-3">
                  <div v-if="m.is_local" class="flex flex-wrap gap-1.5">
                    <span class="px-2 py-0.5 rounded-full text-xs font-medium" :class="authBadgeClass(m.has_session_auth_file, 'session')">
                      Session
                    </span>
                    <span class="px-2 py-0.5 rounded-full text-xs font-medium" :class="authBadgeClass(m.has_rt_auth_file, 'rt')">
                      RT
                    </span>
                    <span class="px-2 py-0.5 rounded-full text-xs font-medium" :class="authBadgeClass(m.has_cpa_uploaded, 'cpa')">
                      CPA
                    </span>
                    <span class="px-2 py-0.5 rounded-full text-xs font-medium" :class="authBadgeClass(m.has_sub2api_sync, 'sub2api')">
                      Sub2API
                    </span>
                  </div>
                  <span v-else class="text-xs text-gray-500">-</span>
                </td>
                <td class="px-4 py-3">
                  <span class="text-xs" :class="m.is_local ? 'text-blue-400' : 'text-gray-500'">
                    {{ sourceLabel(m) }}
                  </span>
                </td>
                <td class="px-4 py-3 text-right">
                  <div class="flex flex-wrap justify-end gap-2">
                  <button
                    v-if="canSell(m)"
                    @click="sellMember(m)"
                    :disabled="actionId === memberKey(m)"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                    :class="actionId === memberKey(m)
                      ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                      : 'bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20'"
                  >
                    {{ actionId === memberKey(m) && actionType === 'sell' ? '处理中...' : '卖出' }}
                  </button>
                  <button
                    v-if="canRemove(m)"
                    @click="removeMember(m)"
                    :disabled="actionId === memberKey(m)"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                    :class="actionId === memberKey(m)
                      ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                      : 'bg-amber-600/10 text-amber-400 border-amber-500/30 hover:bg-amber-600/20'"
                  >
                    {{ actionId === memberKey(m) && actionType === 'remove' ? '处理中...' : removeLabel(m) }}
                  </button>
                  <button
                    v-if="canDelete(m)"
                    @click="deleteMember(m)"
                    :disabled="actionId === memberKey(m)"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                    :class="actionId === memberKey(m)
                      ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                      : 'bg-rose-600/10 text-rose-400 border-rose-500/30 hover:bg-rose-600/20'"
                  >
                    {{ actionId === memberKey(m) && actionType === 'delete' ? '删除中...' : '删除' }}
                  </button>
                  <span v-if="!hasActions(m)" class="text-xs text-gray-600">-</span>
                  </div>
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
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const data = ref(null)
const loading = ref(false)
const error = ref('')
const message = ref('')
const messageClass = ref('')
const actionId = ref('')
const actionType = ref('')

const CACHE_KEY = 'autoteam_team_members'

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (raw) {
      const cached = JSON.parse(raw)
      // 缓存 10 分钟有效
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
  return `${member.type}:${member.user_id}:${member.email}`
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
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function formatCacheTime(ts) {
  const d = new Date(Number(ts) * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatRefreshError(value) {
  if (typeof value === 'string') return value
  return value?.message || JSON.stringify(value)
}

function sourceLabel(member) {
  if (!member.is_local) return '外部'
  return member.status ? `本地管理/${statusLabel(member.status)}` : '本地管理'
}

function statusClass(s) {
  return {
    active: 'bg-green-500/10 text-green-400',
    exhausted: 'bg-red-500/10 text-red-400',
    standby: 'bg-yellow-500/10 text-yellow-400',
    pending: 'bg-gray-500/10 text-gray-400',
    sold: 'bg-cyan-500/10 text-cyan-300',
  }[s] || 'bg-gray-500/10 text-gray-400'
}

function dotClass(s) {
  return {
    active: 'bg-green-400',
    exhausted: 'bg-red-400',
    standby: 'bg-yellow-400',
    pending: 'bg-gray-400',
    sold: 'bg-cyan-300',
  }[s] || 'bg-gray-400'
}

function statusLabel(s) {
  return { active: 'Active', exhausted: 'Used up', standby: 'Standby', pending: 'Pending', sold: 'Sold' }[s] || s || 'Unknown'
}

function authBadgeClass(enabled, type) {
  if (!enabled) return 'bg-gray-700/70 text-gray-400'
  return {
    session: 'bg-sky-500/10 text-sky-300',
    rt: 'bg-emerald-500/10 text-emerald-300',
    cpa: 'bg-cyan-500/10 text-cyan-300',
    sub2api: 'bg-indigo-500/10 text-indigo-300',
  }[type] || 'bg-gray-700/70 text-gray-300'
}

function isOwner(member) {
  return member.role === 'account-owner' || member.is_main_account
}

function isSold(member) {
  return member.status === 'sold' || member.sync_disabled
}

function canSell(member) {
  return member.type === 'member' && member.is_local && member.status === 'active' && !member.sync_disabled && !isOwner(member)
}

function canRemove(member) {
  if (isOwner(member) || isSold(member)) return false
  return member.type === 'invite' || member.type === 'member'
}

function canDelete(member) {
  return member.type === 'member' && member.is_local && !isOwner(member) && !isSold(member)
}

function hasActions(member) {
  return canSell(member) || canRemove(member) || canDelete(member)
}

function removeLabel(member) {
  return member.type === 'invite' ? '取消邀请' : '移出'
}

function showMessage(text, kind = 'success') {
  message.value = text
  messageClass.value = kind === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  setTimeout(() => { message.value = '' }, 8000)
}

async function removeMember(member) {
  const actionText = member.type === 'invite' ? '取消邀请' : '移出 Team'
  const ok = window.confirm(`确认${actionText} ${member.email}？`)
  if (!ok) return

  actionId.value = memberKey(member)
  actionType.value = 'remove'
  error.value = ''
  try {
    const result = await api.removeTeamMember({
      email: member.email,
      user_id: member.user_id,
      type: member.type,
    })
    showMessage(result.message || `已${actionText}: ${member.email}`)
    clearTeamCache()
    await fetchMembers()
  } catch (e) {
    error.value = e.message
  } finally {
    actionId.value = ''
    actionType.value = ''
  }
}

async function sellMember(member) {
  const ok = window.confirm(`确认卖出账号 ${member.email}？\n系统会保留 Team 席位，但会删除 CPA/Sub2API 远端记录，并停止后续同步。`)
  if (!ok) return

  actionId.value = memberKey(member)
  actionType.value = 'sell'
  error.value = ''
  try {
    const result = await api.sellAccount(member.email)
    const archive = result.cpa_archive_file ? `，归档: ${result.cpa_archive_file}` : ''
    showMessage((result.message || `已标记为已售: ${member.email}`) + archive)
    clearTeamCache()
    await fetchMembers({ refresh: true })
  } catch (e) {
    error.value = e.message
  } finally {
    actionId.value = ''
    actionType.value = ''
  }
}

async function deleteMember(member) {
  const ok = window.confirm(`确认删除账号 ${member.email}？\n这会同时清理本地记录、已配置远端、Team/Invite 和邮箱服务账号。`)
  if (!ok) return

  actionId.value = memberKey(member)
  actionType.value = 'delete'
  error.value = ''
  try {
    const result = await api.deleteAccount(member.email)
    showMessage(result.message || `已删除 ${member.email}`)
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
