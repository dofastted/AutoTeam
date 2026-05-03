<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-bold text-white">Team 成员</h2>
        <p class="text-xs text-gray-500 mt-1">显示真实成员和待处理邀请，并合并本地账号状态</p>
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
      <div>{{ message }}</div>
      <div v-if="messageFailures.length" class="mt-2 space-y-1 text-xs">
        <div v-for="item in messageFailures" :key="item.email + item.message" class="text-red-300">
          {{ item.email }}：{{ item.message || item.skipped_reason }}
        </div>
      </div>
    </div>

    <div v-if="data?.cached" class="mb-4 px-4 py-3 rounded-lg text-sm bg-blue-500/10 text-blue-300 border border-blue-500/20">
      当前显示{{ data.local_snapshot ? '本地账号快照' : '本地缓存' }}
      <span v-if="data.cache_updated_at">，更新时间 {{ formatCacheTime(data.cache_updated_at) }}</span>
      <span v-if="data.refresh_error" class="block mt-1 text-amber-300">远端验证失败：{{ formatRefreshError(data.refresh_error) }}</span>
    </div>

    <div v-if="data" class="space-y-5">
      <div class="flex flex-wrap gap-3 text-sm">
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          成员: <span class="text-white font-medium">{{ members.length }}</span>
        </span>
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          邀请: <span class="text-white font-medium">{{ invites.length }}</span>
        </span>
        <span class="px-3 py-1.5 bg-gray-800 rounded-lg text-gray-300">
          每页: <span class="text-white font-medium">{{ pageSize }}</span>
        </span>
      </div>

      <MemberTable
        title="成员"
        empty-text="暂无成员"
        :rows="pagedMembers"
        :page-start="memberPageStart"
        :action-id="actionId"
        :action-type="actionType"
        @action="handleAction"
      />

      <Pager
        v-if="memberTotalPages > 1"
        :page="memberPage"
        :total-pages="memberTotalPages"
        :start="memberPageStart"
        :end="memberPageEnd"
        :total="members.length"
        @go="goMemberPage"
      />

      <MemberTable
        title="邀请"
        empty-text="暂无邀请"
        :rows="pagedInvites"
        :page-start="invitePageStart"
        :action-id="actionId"
        :action-type="actionType"
        @action="handleAction"
      />

      <Pager
        v-if="inviteTotalPages > 1"
        :page="invitePage"
        :total-pages="inviteTotalPages"
        :start="invitePageStart"
        :end="invitePageEnd"
        :total="invites.length"
        @go="goInvitePage"
      />
    </div>

    <div v-else-if="loading" class="bg-gray-900 border border-gray-800 rounded-xl h-64 animate-pulse"></div>

    <div v-else class="text-center text-gray-500 py-12">
      点击「验证刷新」加载 Team 成员列表
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const data = ref(null)
const loading = ref(false)
const error = ref('')
const message = ref('')
const messageClass = ref('')
const messageFailures = ref([])
const actionId = ref('')
const actionType = ref('')
const memberPage = ref(1)
const invitePage = ref(1)
const pageSize = ref(20)

const CACHE_KEY = 'autoteam_team_members'

const members = computed(() => {
  if (!data.value || !Array.isArray(data.value.members)) return []
  return data.value.members.filter((m) => m.type === 'member')
})

const invites = computed(() => {
  if (!data.value || !Array.isArray(data.value.members)) return []
  return data.value.members.filter((m) => m.type === 'invite')
})

const memberTotalPages = computed(() => Math.max(1, Math.ceil(members.value.length / pageSize.value)))
const inviteTotalPages = computed(() => Math.max(1, Math.ceil(invites.value.length / pageSize.value)))
const memberPageStart = computed(() => (memberPage.value - 1) * pageSize.value)
const invitePageStart = computed(() => (invitePage.value - 1) * pageSize.value)
const memberPageEnd = computed(() => Math.min(members.value.length, memberPageStart.value + pageSize.value))
const invitePageEnd = computed(() => Math.min(invites.value.length, invitePageStart.value + pageSize.value))
const pagedMembers = computed(() => members.value.slice(memberPageStart.value, memberPageEnd.value))
const pagedInvites = computed(() => invites.value.slice(invitePageStart.value, invitePageEnd.value))

const Pager = defineComponent({
  props: {
    page: { type: Number, required: true },
    totalPages: { type: Number, required: true },
    start: { type: Number, required: true },
    end: { type: Number, required: true },
    total: { type: Number, required: true },
  },
  emits: ['go'],
  setup(props, { emit }) {
    return () => h('div', { class: 'px-4 py-3 border border-gray-800 border-t-0 rounded-b-xl flex items-center justify-between' }, [
      h('div', { class: 'text-xs text-gray-500' }, `显示 ${props.start + 1} - ${props.end} / ${props.total}`),
      h('div', { class: 'flex items-center gap-2' }, [
        pagerButton('首页', props.page === 1, () => emit('go', 1)),
        pagerButton('上一页', props.page === 1, () => emit('go', props.page - 1)),
        h('span', { class: 'text-xs text-gray-400 px-2' }, `${props.page} / ${props.totalPages}`),
        pagerButton('下一页', props.page >= props.totalPages, () => emit('go', props.page + 1)),
        pagerButton('末页', props.page >= props.totalPages, () => emit('go', props.totalPages)),
      ]),
    ])
  },
})

const MemberTable = defineComponent({
  props: {
    title: { type: String, required: true },
    emptyText: { type: String, required: true },
    rows: { type: Array, required: true },
    pageStart: { type: Number, required: true },
    actionId: { type: String, required: true },
    actionType: { type: String, required: true },
  },
  emits: ['action'],
  setup(props, { emit }) {
    return () => h('div', { class: 'bg-gray-900 border border-gray-800 rounded-xl overflow-hidden' }, [
      h('div', { class: 'px-4 py-3 border-b border-gray-800 text-sm font-medium text-gray-200' }, props.title),
      h('div', { class: 'overflow-x-auto' }, [
        h('table', { class: 'w-full text-sm' }, [
          h('thead', [
            h('tr', { class: 'text-gray-400 text-left border-b border-gray-800' }, [
              tableHead('#', 'w-12'),
              tableHead('邮箱', ''),
              tableHead('类型', 'w-24'),
              tableHead('角色/状态', 'w-40'),
              tableHead('加入/邀请时间', 'w-48'),
              tableHead('本地账号状态', 'w-36'),
              tableHead('操作', 'w-56 text-right'),
            ]),
          ]),
          h('tbody', [
            ...props.rows.map((row, index) => h('tr', {
              key: memberKey(row),
              class: 'border-b border-gray-800/50 hover:bg-gray-800/30 transition',
            }, [
              h('td', { class: 'px-4 py-3 text-gray-500' }, String(props.pageStart + index + 1)),
              h('td', { class: 'px-4 py-3 font-mono text-xs text-gray-200' }, row.email || '-'),
              h('td', { class: 'px-4 py-3' }, [badge(row.type === 'invite' ? '邀请' : '成员', row.type === 'invite' ? 'amber' : 'blue')]),
              h('td', { class: 'px-4 py-3' }, [badge(row.type === 'invite' ? (row.role || 'pending') : (row.role || 'member'), roleTone(row))]),
              h('td', { class: 'px-4 py-3 text-xs text-gray-400' }, formatJoinedAt(row.joined_at)),
              h('td', { class: 'px-4 py-3' }, [localStatus(row)]),
              h('td', { class: 'px-4 py-3 text-right' }, actionButtons(row, props, emit)),
            ])),
            props.rows.length ? null : h('tr', [
              h('td', { colspan: 7, class: 'px-4 py-12 text-center text-gray-500 text-sm' }, props.emptyText),
            ]),
          ]),
        ]),
      ]),
    ])
  },
})

function pagerButton(label, disabled, onClick) {
  return h('button', {
    disabled,
    onClick,
    class: 'px-2 py-1 text-xs rounded border border-gray-700 bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed',
  }, label)
}

function tableHead(label, widthClass) {
  return h('th', { class: `px-4 py-3 font-medium ${widthClass}` }, label)
}

function badge(text, tone) {
  const classes = {
    blue: 'bg-blue-500/10 text-blue-400',
    amber: 'bg-amber-500/10 text-amber-300',
    purple: 'bg-purple-500/10 text-purple-400',
    green: 'bg-green-500/10 text-green-400',
    cyan: 'bg-cyan-500/10 text-cyan-300',
    red: 'bg-red-500/10 text-red-400',
    gray: 'bg-gray-500/10 text-gray-300',
  }
  return h('span', { class: `px-2 py-0.5 rounded text-xs font-medium ${classes[tone] || classes.gray}` }, text || '-')
}

function roleTone(row) {
  if (row.role === 'account-owner') return 'purple'
  if (row.role === 'account-admin') return 'blue'
  if (row.type === 'invite') return 'amber'
  return 'gray'
}

function localStatus(row) {
  if (!row.is_local) return badge('外部', 'gray')
  if (row.sync_disabled) return badge(`${row.status || 'disabled'} / 禁用同步`, 'red')
  return badge(row.status || '本地', row.status === 'active' ? 'green' : 'gray')
}

function actionButtons(row, props, emit) {
  const actions = allowedActions(row)
  if (!actions.length) {
    return h('span', { class: 'text-xs text-gray-600' }, readOnlyReason(row))
  }
  return h('div', { class: 'flex justify-end gap-2' }, actions.map((action) => {
    const key = memberKey(row)
    const busy = props.actionId === key && props.actionType === action
    return h('button', {
      disabled: Boolean(props.actionId),
      onClick: () => emit('action', action, row),
      class: `${actionClass(action)} disabled:opacity-50 disabled:cursor-not-allowed`,
    }, busy ? '处理中...' : actionText(action))
  }))
}

function actionClass(action) {
  const base = 'px-3 py-1.5 rounded-lg text-xs font-medium border transition'
  if (action === 'delete') return `${base} bg-red-600/10 text-red-300 border-red-500/30 hover:bg-red-600/20`
  if (action === 'sell') return `${base} bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20`
  return `${base} bg-amber-600/10 text-amber-400 border-amber-500/30 hover:bg-amber-600/20`
}

function actionText(action) {
  return {
    'remove-team': '移出',
    'cancel-invite': '取消邀请',
    sell: '卖出',
    delete: '删除',
  }[action] || action
}

function readOnlyReason(row) {
  if (isOwner(row)) return 'owner/main'
  if (row.status === 'sold') return '已售'
  if (row.sync_disabled) return '同步禁用'
  return '-'
}

function allowedActions(row) {
  if (isOwner(row) || row.status === 'sold' || row.sync_disabled) return []
  const actions = []
  if (row.type === 'member') actions.push('remove-team')
  if (row.type === 'invite') actions.push('cancel-invite')
  if (row.is_local && row.status === 'active') actions.push('sell')
  if (row.is_local && !row.is_main_account) actions.push('delete')
  return actions
}

watch(members, () => {
  if (memberPage.value > memberTotalPages.value) memberPage.value = memberTotalPages.value
  if (memberPage.value < 1) memberPage.value = 1
})

watch(invites, () => {
  if (invitePage.value > inviteTotalPages.value) invitePage.value = inviteTotalPages.value
  if (invitePage.value < 1) invitePage.value = 1
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
    if (memberPage.value > memberTotalPages.value) memberPage.value = 1
    if (invitePage.value > inviteTotalPages.value) invitePage.value = 1
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function goMemberPage(p) {
  if (p < 1 || p > memberTotalPages.value) return
  memberPage.value = p
}

function goInvitePage(p) {
  if (p < 1 || p > inviteTotalPages.value) return
  invitePage.value = p
}

function formatCacheTime(ts) {
  const d = new Date(Number(ts) * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatJoinedAt(value) {
  if (!value) return '-'
  let d
  if (typeof value === 'number') {
    d = new Date(value < 1e12 ? value * 1000 : value)
  } else if (typeof value === 'string') {
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

function showMessage(text, kind = 'success', failures = []) {
  message.value = text
  messageFailures.value = failures.slice(0, 5)
  messageClass.value = kind === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  setTimeout(() => {
    message.value = ''
    messageFailures.value = []
  }, 9000)
}

function actionConfirmText(action, row) {
  const base = {
    'remove-team': `确认将 ${row.email} 移出 Team？`,
    'cancel-invite': `确认取消 ${row.email} 的邀请？`,
    sell: `确认将 ${row.email} 标记为已售？会清理已启用 CPA / Sub2API 远端记录。`,
    delete: `确认删除 ${row.email}？会删除本地账号及关联资源，并可能改变远端状态。`,
  }[action]
  return base || `确认操作 ${row.email}？`
}

function actionPayload(action, row) {
  return {
    action,
    confirm: true,
    items: [{
      email: row.email,
      user_id: row.user_id,
      type: row.type,
      plan_type: 'team',
      is_team_plan: true,
    }],
    options: action === 'delete' ? { sync_cpa_after: true } : {},
  }
}

async function handleAction(action, row) {
  if (!window.confirm(actionConfirmText(action, row))) return
  actionId.value = memberKey(row)
  actionType.value = action
  error.value = ''
  try {
    const result = await api.bulkAccountAction(actionPayload(action, row))
    const rows = result.results || []
    const success = rows.filter((item) => item.ok && item.status === 'done').length
    const skipped = rows.filter((item) => item.status === 'skipped').length
    const failed = rows.filter((item) => item.status === 'failed').length
    const failures = rows.filter((item) => item.status === 'failed' || item.status === 'skipped')
    showMessage(`${actionText(action)}完成：成功 ${success}，跳过 ${skipped}，失败 ${failed}`, failed ? 'error' : 'success', failures)
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
