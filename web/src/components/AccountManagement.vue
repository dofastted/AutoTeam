<template>
  <div class="space-y-5">
    <div class="glass-card overflow-hidden">
      <div class="border-b border-white/10 px-5 py-5">
        <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div class="space-y-2">
            <div class="section-heading text-lg">账号管理中心</div>
            <p class="section-subtitle max-w-2xl">
              按五类账号切换列表，点击行后在右侧抽屉里查看详情、修复认证和处理状态。
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              type="button"
              class="rounded-2xl px-4 py-2 text-sm transition"
              :class="activeTab === tab.key
                ? 'bg-blue-500/20 text-white ring-1 ring-blue-400/40'
                : 'bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'"
              @click="setActiveTab(tab.key)"
            >
              {{ tab.icon }} {{ tab.label }}
            </button>
          </div>
        </div>
      </div>

      <div class="px-5 py-4">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div class="text-sm text-slate-400">
            当前分类：
            <span class="font-medium text-slate-200">{{ activeTabMeta.label }}</span>
            <span class="mx-2 text-slate-600">·</span>
            <span>{{ activeTabMeta.hint }}</span>
          </div>
          <button
            type="button"
            class="btn-secondary text-sm"
            :disabled="loading"
            @click="handleRefresh"
          >
            {{ loading ? '刷新中...' : '刷新父级数据' }}
          </button>
        </div>
      </div>
    </div>

    <AccountTable
      :category="activeTab"
      :refresh-key="refreshKey"
      @select-account="onSelectAccount"
      @refresh-needed="bumpRefresh"
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
import { computed, ref } from 'vue'
import AccountDrawer from './AccountDrawer.vue'
import AccountTable from './AccountTable.vue'

const props = defineProps({
  loading: Boolean,
})

const emit = defineEmits(['refresh'])

const tabs = [
  { key: 'registered', icon: '✅', label: '已注册', hint: '已完成注册但还没进入库存、自用或已售视角。' },
  { key: 'inventory', icon: '📦', label: '库存', hint: '最常用的库存池，默认先看这里。' },
  { key: 'in_use', icon: '🔵', label: '使用中', hint: '当前已经分配出去，正在被项目或成员使用。' },
  { key: 'invalid', icon: '🚨', label: '失效', hint: '认证、额度或账号状态异常，需要排查。' },
  { key: 'sold', icon: '💰', label: '已售', hint: '已售账号只做记录和远端清理确认。' },
]

const activeTab = ref('inventory')
const refreshKey = ref(0)
const drawerOpen = ref(false)
const drawerEmail = ref('')

const activeTabMeta = computed(() => {
  return tabs.find((tab) => tab.key === activeTab.value) || tabs[1]
})

function setActiveTab(tabKey) {
  activeTab.value = tabKey
}

function onSelectAccount(account) {
  drawerEmail.value = account?.email || ''
  drawerOpen.value = Boolean(drawerEmail.value)
}

function bumpRefresh() {
  refreshKey.value += 1
}

function handleDrawerActionDone() {
  bumpRefresh()
}

function handleRefresh() {
  if (props.loading) {
    return
  }
  emit('refresh')
  bumpRefresh()
}
</script>
