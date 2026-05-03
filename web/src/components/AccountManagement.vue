<template>
  <div class="space-y-5">
    <div class="bg-gray-900 border border-gray-800 rounded-xl px-5 py-5">
      <div class="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div class="space-y-1">
          <div class="text-lg font-semibold text-white">账号管理</div>
          <p class="text-sm text-gray-400 max-w-2xl">
            本地账号表来自 <code class="text-xs px-1 bg-gray-800 rounded">accounts.json</code>，用于登录、移出、已售、删除、导出和详情操作。
            下方认证文件盘点扫描 <code class="text-xs px-1 bg-gray-800 rounded">auths/</code>，用于核对文件和批量处理 Team 认证记录。
          </p>
        </div>
        <button
          type="button"
          class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-300"
          :disabled="loading"
          @click="handleRefresh"
        >
          {{ loading ? '刷新中...' : '刷新数据' }}
        </button>
      </div>
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
      <div class="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div class="text-base font-semibold text-white">本地账号</div>
          <div class="text-sm text-gray-400 mt-1">点击行查看账号详情；操作列提供账号管理动作。</div>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="item in categories"
            :key="item.value"
            type="button"
            class="px-3 py-1.5 rounded-lg border text-xs transition"
            :class="accountCategory === item.value
              ? 'bg-blue-600/20 text-blue-200 border-blue-500/40'
              : 'bg-gray-800 text-gray-400 border-gray-700 hover:bg-gray-700 hover:text-gray-200'"
            @click="setAccountCategory(item.value)"
          >
            {{ item.label }}
          </button>
        </div>
      </div>
    </div>

    <AccountTable
      :category="accountCategory"
      :refresh-key="refreshKey"
      @select-account="onSelectAccount"
      @refresh-needed="bumpRefresh"
    />

    <div class="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
      <div class="text-base font-semibold text-white">认证文件盘点</div>
      <div class="text-sm text-gray-400 mt-1">
        按邮箱聚合 <code class="text-xs px-1 bg-gray-800 rounded">auths/</code> 文件。仅有认证文件但未写入本地账号池的邮箱，不会打开账号详情。
      </div>
    </div>

    <AuthsTable
      :refresh-key="refreshKey"
      @bulk-complete="handleBulkComplete"
    />

    <AccountDrawer
      :open="drawerOpen"
      :email="drawerEmail"
      @close="drawerOpen = false"
      @action-done="handleDrawerActionDone"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountDrawer from './AccountDrawer.vue'
import AccountTable from './AccountTable.vue'
import AuthsTable from './AuthsTable.vue'

const props = defineProps({
  loading: Boolean,
})

const emit = defineEmits(['refresh'])

const refreshKey = ref(0)
const drawerOpen = ref(false)
const drawerEmail = ref('')
const accountCategory = ref('all')
const categories = [
  { value: 'all', label: '全部' },
  { value: 'registered', label: '已注册' },
  { value: 'inventory', label: '库存' },
  { value: 'in_use', label: '使用中' },
  { value: 'invalid', label: '失效' },
  { value: 'sold', label: '已售' },
  { value: 'not_registered', label: '未注册' },
]

function onSelectAccount(account) {
  drawerEmail.value = account?.email || ''
  drawerOpen.value = Boolean(drawerEmail.value)
}

function bumpRefresh() {
  refreshKey.value += 1
}

function setAccountCategory(category) {
  accountCategory.value = category
}

function handleDrawerActionDone() {
  bumpRefresh()
}

function handleBulkComplete() {
  bumpRefresh()
  if (drawerOpen.value) {
    drawerOpen.value = false
    drawerEmail.value = ''
  }
}

function handleRefresh() {
  if (props.loading) return
  emit('refresh')
  bumpRefresh()
}
</script>
