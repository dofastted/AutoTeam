<template>
  <div class="space-y-4">
    <div class="glass-card overflow-hidden">
      <div class="border-b border-white/10 px-4 py-4 sm:px-5">
        <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div class="section-heading text-lg">auth 文件记录</div>
            <div class="section-subtitle">
              只读文件扫描视图。筛选和排序直接传给 /api/auths/accounts。
            </div>
          </div>
          <div class="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-300">
            <span class="h-2 w-2 rounded-full bg-indigo-300 shadow-[0_0_14px_rgba(129,140,248,0.85)]"></span>
            共 <span class="font-semibold text-white">{{ total }}</span> 个邮箱
            <span v-if="loading" class="text-indigo-200">加载中...</span>
          </div>
        </div>
      </div>

      <div class="px-4 py-4 sm:px-5">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div>
          <label class="mb-1.5 block text-xs font-medium text-slate-500">分类</label>
          <select v-model="filterCategory" @change="applyFilters"
            class="input-dark">
            <option value="">全部（不含归档）</option>
            <option value="active">活跃</option>
            <option value="sold">已售</option>
            <option value="tradable">可交易</option>
            <option value="unusable">不可用</option>
            <option value="archive">归档</option>
            <option value="all">全部含归档</option>
          </select>
        </div>
        <div>
          <label class="mb-1.5 block text-xs font-medium text-slate-500">OAuth 文件</label>
          <select v-model="filterOauth" @change="applyFilters"
            class="input-dark">
            <option value="">全部</option>
            <option value="true">有</option>
            <option value="false">无</option>
          </select>
        </div>
        <div>
          <label class="mb-1.5 block text-xs font-medium text-slate-500">Session 文件</label>
          <select v-model="filterSession" @change="applyFilters"
            class="input-dark">
            <option value="">全部</option>
            <option value="true">有</option>
            <option value="false">无</option>
          </select>
        </div>
        <div>
          <label class="mb-1.5 block text-xs font-medium text-slate-500">排序</label>
          <select v-model="sort" @change="applyFilters"
            class="input-dark">
            <option value="email_asc">邮箱 ↑</option>
            <option value="email_desc">邮箱 ↓</option>
            <option value="expired_asc">过期 ↑</option>
            <option value="expired_desc">过期 ↓</option>
            <option value="category_asc">分类 ↑</option>
          </select>
        </div>
        <div>
          <label class="mb-1.5 block text-xs font-medium text-slate-500">搜索邮箱</label>
          <input v-model="searchQ" @keyup.enter="applyFilters" @blur="applyFilters" type="text"
            placeholder="包含的邮箱字符串..."
            class="input-dark" />
        </div>
      </div>

        <div v-if="facets" class="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <span
            v-for="facet in facetItems"
            :key="facet.key"
            class="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-400"
          >
            <span class="block text-slate-500">{{ facet.label }}</span>
            <b class="mt-1 block text-base font-semibold" :class="facet.className">
              {{ facets[facet.key] || 0 }}
            </b>
          </span>
        </div>
      </div>
    </div>

    <div v-if="error" class="rounded-2xl border border-rose-500/30 bg-rose-950/50 px-4 py-3 text-sm text-rose-100">
      {{ error }}
    </div>

    <div class="glass-card overflow-hidden">
      <div class="flex flex-col gap-3 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div class="text-sm text-slate-400">
          文件盘点结果
          <span class="mx-1 text-slate-600">/</span>
          第 {{ page }} 页
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <label class="text-xs text-slate-500">每页</label>
          <select v-model.number="pageSize" @change="onPageSizeChange"
            class="input-dark w-24 py-2 text-xs">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="200">200</option>
          </select>
          <button @click="reload" :disabled="loading"
            class="btn-secondary px-3 py-2 text-xs">
            刷新
          </button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="border-b border-white/10 text-left text-slate-400">
              <th class="px-4 py-3 font-medium w-12">#</th>
              <th class="px-4 py-3 font-medium">邮箱</th>
              <th class="px-4 py-3 font-medium w-28">分类</th>
              <th class="px-4 py-3 font-medium w-24 text-center">OAuth</th>
              <th class="px-4 py-3 font-medium w-24 text-center">Session</th>
              <th class="px-4 py-3 font-medium w-24 text-center">已禁用</th>
              <th class="px-4 py-3 font-medium w-44">过期时间</th>
              <th class="px-4 py-3 font-medium w-32">凭证来源</th>
              <th class="px-4 py-3 font-medium w-20 text-center">文件数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in records" :key="r.email + ':' + r.team_hash"
              class="border-b border-white/5 transition hover:bg-white/[0.04]">
              <td class="px-4 py-3 text-slate-500">{{ pageStart + i + 1 }}</td>
              <td class="px-4 py-3 font-mono text-xs text-slate-100">{{ r.email }}</td>
              <td class="px-4 py-3">
                <span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-medium" :class="categoryClass(r.category)">
                  {{ categoryLabel(r.category) }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-medium"
                  :class="r.has_oauth ? 'border-indigo-400/20 bg-indigo-500/10 text-indigo-200' : 'border-white/10 bg-white/[0.04] text-slate-500'">
                  {{ r.has_oauth ? '有' : '无' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-medium"
                  :class="r.has_session ? 'border-violet-400/20 bg-violet-500/10 text-violet-200' : 'border-white/10 bg-white/[0.04] text-slate-500'">
                  {{ r.has_session ? '有' : '无' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span v-if="r.disabled === true" class="inline-flex rounded-full border border-rose-400/20 bg-rose-500/10 px-2.5 py-1 text-xs text-rose-200">是</span>
                <span v-else-if="r.disabled === false" class="inline-flex rounded-full border border-emerald-400/20 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200">否</span>
                <span v-else class="text-xs text-slate-600">-</span>
              </td>
              <td class="px-4 py-3 text-xs text-slate-400">{{ formatDate(r.expired) }}</td>
              <td class="px-4 py-3 text-xs text-slate-400">{{ r.credential_source || '-' }}</td>
              <td class="px-4 py-3 text-center text-xs text-slate-400">{{ r.file_count }}</td>
            </tr>
            <tr v-if="!records.length && !loading">
              <td colspan="9" class="px-4 py-12 text-center text-sm text-slate-500">
                没有符合条件的账号
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="totalPages > 1" class="flex flex-col gap-3 border-t border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div class="text-xs text-slate-500">
          显示 {{ pageStart + 1 }} - {{ pageEnd }} / {{ total }}
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button @click="goToPage(1)" :disabled="page === 1 || loading"
            class="btn-secondary px-2.5 py-1.5 text-xs">
            首页
          </button>
          <button @click="goToPage(page - 1)" :disabled="page === 1 || loading"
            class="btn-secondary px-2.5 py-1.5 text-xs">
            上一页
          </button>
          <span class="px-2 text-xs text-slate-400">{{ page }} / {{ totalPages }}</span>
          <button @click="goToPage(page + 1)" :disabled="page >= totalPages || loading"
            class="btn-secondary px-2.5 py-1.5 text-xs">
            下一页
          </button>
          <button @click="goToPage(totalPages)" :disabled="page >= totalPages || loading"
            class="btn-secondary px-2.5 py-1.5 text-xs">
            末页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const filterCategory = ref('')
const filterOauth = ref('')
const filterSession = ref('')
const sort = ref('email_asc')
const searchQ = ref('')
const page = ref(1)
const pageSize = ref(20)

const records = ref([])
const total = ref(0)
const facets = ref(null)
const loading = ref(false)
const error = ref('')

const facetItems = [
  { key: 'active', label: '活跃', className: 'text-emerald-200' },
  { key: 'sold', label: '已售', className: 'text-cyan-200' },
  { key: 'tradable', label: '可交易', className: 'text-lime-200' },
  { key: 'unusable', label: '不可用', className: 'text-rose-200' },
  { key: 'archive', label: '归档', className: 'text-slate-300' },
]

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const pageStart = computed(() => (page.value - 1) * pageSize.value)
const pageEnd = computed(() => Math.min(total.value, pageStart.value + records.value.length))

watch(() => props.refreshKey, () => {
  reload()
})

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    }
    if (filterCategory.value) params.category = filterCategory.value
    if (filterOauth.value !== '') params.has_oauth = filterOauth.value === 'true'
    if (filterSession.value !== '') params.has_session = filterSession.value === 'true'
    if (searchQ.value.trim()) params.q = searchQ.value.trim()

    const resp = await api.getAuthsAccounts(params)
    records.value = resp.items || []
    total.value = resp.total || 0
    facets.value = resp.facets?.category || null
  } catch (e) {
    error.value = e.message
    records.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  reload()
}

function onPageSizeChange() {
  page.value = 1
  reload()
}

function goToPage(p) {
  if (p < 1 || p > totalPages.value || loading.value) return
  page.value = p
  reload()
}

function categoryLabel(c) {
  return {
    active: '活跃',
    sold: '已售',
    tradable: '可交易',
    unusable: '不可用',
    archive: '归档',
  }[c] || c || '未知'
}

function categoryClass(c) {
  return {
    active: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
    sold: 'border-cyan-400/20 bg-cyan-500/10 text-cyan-200',
    tradable: 'border-lime-400/20 bg-lime-500/10 text-lime-200',
    unusable: 'border-rose-400/20 bg-rose-500/10 text-rose-200',
    archive: 'border-slate-400/20 bg-slate-500/10 text-slate-300',
  }[c] || 'border-white/10 bg-white/[0.04] text-slate-300'
}

function formatDate(value) {
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
  if (Number.isNaN(d.getTime())) return String(value)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

onMounted(() => {
  reload()
})
</script>
