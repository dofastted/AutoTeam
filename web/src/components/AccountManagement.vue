<template>
  <section class="account-workspace">
    <div class="account-workspace__ambient" aria-hidden="true"></div>

    <div class="account-workspace__hero">
      <div class="min-w-0 space-y-4">
        <div class="inline-flex w-fit items-center gap-2 rounded-full border border-indigo-300/20 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-100">
          <span class="h-1.5 w-1.5 rounded-full bg-indigo-300 shadow-[0_0_18px_rgba(129,140,248,0.95)]"></span>
          独立账号工作台
        </div>
        <div class="space-y-3">
          <h2 class="max-w-4xl text-3xl font-semibold leading-tight text-white md:text-4xl">
            账号生命周期、库存动作和 auth 文件盘点分区处理
          </h2>
          <p class="max-w-3xl text-sm leading-6 text-slate-400 md:text-base">
            左侧控制当前工作视图，右侧处理本地账号表和认证文件盘点。生命周期数据来自
            <code class="account-code">/api/accounts</code>，auth 文件盘点来自
            <code class="account-code">/api/auths/accounts</code>。账号清理保留 dry-run、预览和 apply 三步流，但只在工作台内部打开。
          </p>
        </div>
      </div>

      <div class="account-hero-actions">
        <div class="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3">
          <div class="text-xs uppercase text-slate-500">当前生命周期分类</div>
          <div class="mt-1 text-lg font-semibold text-white">{{ activeCategory.label }}</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">{{ activeCategory.hint }}</div>
        </div>
        <button
          type="button"
          class="btn-primary min-h-11 px-5"
          :disabled="loading"
          @click="handleRefresh"
        >
          {{ loading ? '刷新中...' : '刷新工作台' }}
        </button>
      </div>
    </div>

    <div class="account-workspace__grid">
      <aside class="account-control-rail" aria-label="账号管理工作区控制">
        <div class="space-y-2">
          <div class="px-1 text-xs font-medium uppercase text-slate-500">工作视图</div>
          <button
            v-for="view in workspaceViews"
            :key="view.value"
            type="button"
            class="account-view-button"
            :class="{ 'account-view-button--active': activeView === view.value }"
            :aria-pressed="activeView === view.value"
            @click="setActiveView(view.value)"
          >
            <span class="account-view-button__icon" aria-hidden="true">{{ view.index }}</span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium">{{ view.label }}</span>
              <span class="mt-0.5 block text-xs leading-5 text-slate-500">{{ view.hint }}</span>
            </span>
          </button>
        </div>

        <div class="space-y-3">
          <div class="px-1 text-xs font-medium uppercase text-slate-500">生命周期分类</div>
          <div class="grid gap-2">
            <button
              v-for="item in categories"
              :key="item.value"
              type="button"
              class="account-category-button"
              :class="{ 'account-category-button--active': accountCategory === item.value }"
              :aria-pressed="accountCategory === item.value"
              @click="setAccountCategory(item.value)"
            >
              <span class="account-category-button__dot" :class="item.dotClass"></span>
              <span class="min-w-0">
                <span class="block truncate text-sm font-medium">{{ item.label }}</span>
                <span class="block truncate text-xs text-slate-500">{{ item.hint }}</span>
              </span>
            </button>
          </div>
        </div>

        <div class="account-boundary-card">
          <div class="text-sm font-semibold text-white">边界说明</div>
          <dl class="mt-3 space-y-3 text-xs leading-5 text-slate-400">
            <div>
              <dt class="text-slate-200">生命周期表</dt>
              <dd>可打开详情抽屉，并保留登录、导出、移出 Team、已售和删除动作。</dd>
            </div>
            <div>
              <dt class="text-slate-200">auth 文件盘点</dt>
              <dd>只扫描文件系统，不打开账号详情，不接危险操作。</dd>
            </div>
            <div>
              <dt class="text-slate-200">账号清理</dt>
              <dd>工作台内置 dry-run、预览、CSV、完整 JSON、apply 确认和复扫结果。</dd>
            </div>
            <div>
              <dt class="text-slate-200">RT 恢复</dt>
              <dd>归类缺 RT、401 和 Deactivated 账号，恢复动作只在确认后启动。</dd>
            </div>
          </dl>
        </div>
      </aside>

      <main class="min-w-0 space-y-4">
        <div class="account-panel-switcher" role="tablist" aria-label="账号管理视图切换">
          <button
            v-for="view in workspaceViews"
            :key="view.value"
            type="button"
            class="account-panel-tab"
            :class="{ 'account-panel-tab--active': activeView === view.value }"
            :id="`${view.value}-tab`"
            :aria-controls="`${view.value}-panel`"
            :aria-selected="activeView === view.value"
            :tabindex="activeView === view.value ? 0 : -1"
            role="tab"
            @click="setActiveView(view.value)"
            @keydown="handleTabKeydown($event, view.value)"
          >
            {{ view.label }}
          </button>
        </div>

        <section
          v-show="activeView === 'lifecycle'"
          id="lifecycle-panel"
          class="space-y-4"
          role="tabpanel"
          aria-labelledby="lifecycle-tab"
          :aria-hidden="activeView !== 'lifecycle'"
        >
          <div class="account-section-head">
            <div>
              <p class="account-section-kicker">/api/accounts</p>
              <h3 class="account-section-title">本地账号生命周期</h3>
              <p class="account-section-copy">
                点击生命周期表的账号行打开详情抽屉；操作按钮沿用原有禁用规则，主号、已售、非 active 账号仍按原逻辑限制。
              </p>
            </div>
            <div class="account-section-badge">
              当前：{{ activeCategory.label }}
            </div>
          </div>

          <AccountTable
            :category="accountCategory"
            :refresh-key="refreshKey"
            @select-account="onSelectAccount"
            @refresh-needed="bumpRefresh"
          />
        </section>

        <section
          v-show="activeView === 'auths'"
          id="auths-panel"
          class="space-y-4"
          role="tabpanel"
          aria-labelledby="auths-tab"
          :aria-hidden="activeView !== 'auths'"
        >
          <div class="account-section-head">
            <div>
              <p class="account-section-kicker">/api/auths/accounts</p>
              <h3 class="account-section-title">认证文件盘点</h3>
              <p class="account-section-copy">
                按邮箱聚合 <code class="account-code">auths/</code> 文件，支持 category、OAuth、Session、排序、搜索和分页。auth-only 邮箱只作为文件记录展示。
              </p>
            </div>
            <div class="account-section-badge">
              只读盘点
            </div>
          </div>

          <AuthsTable :refresh-key="refreshKey" />
        </section>

        <section
          v-show="activeView === 'clean'"
          id="clean-panel"
          class="space-y-4"
          role="tabpanel"
          aria-labelledby="clean-tab"
          :aria-hidden="activeView !== 'clean'"
        >
          <div class="account-section-head">
            <div>
              <p class="account-section-kicker">/api/accounts/clean</p>
              <h3 class="account-section-title">账号清理</h3>
              <p class="account-section-copy">
                先扫描 <code class="account-code">accounts.json</code>，再预览重复邮箱、缺文件、错误 auth 引用等风险。应用前仍会弹出确认，后端会自动备份并复扫。
              </p>
            </div>
            <div class="account-section-badge">
              dry-run 优先
            </div>
          </div>

          <AccountCleanPage :loading="loading" @refresh="handleEmbeddedCleanRefresh" />
        </section>

        <section
          v-show="activeView === 'rt-recovery'"
          id="rt-recovery-panel"
          class="space-y-4"
          role="tabpanel"
          aria-labelledby="rt-recovery-tab"
          :aria-hidden="activeView !== 'rt-recovery'"
        >
          <div class="account-section-head">
            <div>
              <p class="account-section-kicker">/api/accounts/rt-recovery</p>
              <h3 class="account-section-title">RT 恢复</h3>
              <p class="account-section-copy">
                扫描注册完成但缺少 OAuth RT 的账号，401 账号可重新跑 RT 获取；错误包含 Deactivated 的账号只标记失效。
              </p>
            </div>
            <div class="account-section-badge">
              手动启动
            </div>
          </div>

          <AccountRtRecoveryPanel @refresh="handleEmbeddedCleanRefresh" />
        </section>
      </main>
    </div>

    <AccountDrawer
      :open="drawerOpen"
      :email="drawerEmail"
      @close="drawerOpen = false"
      @action-done="handleDrawerActionDone"
    />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import AccountDrawer from './AccountDrawer.vue'
import AccountCleanPage from './AccountCleanPage.vue'
import AccountRtRecoveryPanel from './AccountRtRecoveryPanel.vue'
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
const activeView = ref('lifecycle')

const workspaceViews = [
  { value: 'lifecycle', index: '01', label: '生命周期表', hint: '本地账号详情与动作' },
  { value: 'auths', index: '02', label: 'auth 文件盘点', hint: '只读认证文件扫描' },
  { value: 'clean', index: '03', label: '账号清理', hint: '扫描、预览和应用清理' },
  { value: 'rt-recovery', index: '04', label: 'RT 恢复', hint: '缺 RT、401 和失效归类' },
]

const categories = [
  { value: 'all', label: '全部', hint: '完整账号池', dotClass: 'bg-slate-300' },
  { value: 'registered', label: '已注册', hint: '已完成注册', dotClass: 'bg-sky-300' },
  { value: 'inventory', label: '库存', hint: '可分配账号', dotClass: 'bg-emerald-300' },
  { value: 'in_use', label: '使用中', hint: '已分配使用', dotClass: 'bg-indigo-300' },
  { value: 'invalid', label: '失效', hint: '需修复或隔离', dotClass: 'bg-rose-300' },
  { value: 'sold', label: '已售', hint: '已下架售出', dotClass: 'bg-fuchsia-300' },
  { value: 'not_registered', label: '未注册', hint: '注册未完成', dotClass: 'bg-amber-300' },
]

const activeCategory = computed(() => categories.find((item) => item.value === accountCategory.value) || categories[0])

function onSelectAccount(account) {
  drawerEmail.value = account?.email || ''
  drawerOpen.value = Boolean(drawerEmail.value)
}

function bumpRefresh() {
  refreshKey.value += 1
}

function setAccountCategory(category) {
  accountCategory.value = category
  activeView.value = 'lifecycle'
}

function setActiveView(view) {
  activeView.value = view
}

function handleTabKeydown(event, currentView) {
  const currentIndex = workspaceViews.findIndex((view) => view.value === currentView)
  if (currentIndex < 0) return

  let nextIndex = currentIndex
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    nextIndex = (currentIndex + 1) % workspaceViews.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    nextIndex = (currentIndex - 1 + workspaceViews.length) % workspaceViews.length
  } else if (event.key === 'Home') {
    nextIndex = 0
  } else if (event.key === 'End') {
    nextIndex = workspaceViews.length - 1
  } else {
    return
  }

  event.preventDefault()
  activeView.value = workspaceViews[nextIndex].value
  requestAnimationFrame(() => {
    document.getElementById(`${workspaceViews[nextIndex].value}-tab`)?.focus()
  })
}

function handleDrawerActionDone() {
  bumpRefresh()
}

function handleEmbeddedCleanRefresh() {
  emit('refresh')
  bumpRefresh()
}

function handleRefresh() {
  if (props.loading) return
  emit('refresh')
  bumpRefresh()
}
</script>
