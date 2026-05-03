<template>
  <div class="mt-6 space-y-6">
    <div class="glass-card overflow-hidden p-6">
      <div class="pointer-events-none absolute"></div>
      <div class="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-500/10 px-4 py-2 text-sm text-blue-200">
            <span class="inline-block h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_14px_rgba(34,211,238,0.9)]"></span>
            AutoTeam Configuration Center
          </div>
          <h2 class="section-heading">配置面板</h2>
          <p class="section-subtitle max-w-2xl">
            按邮箱服务、远端同步、代理、安全、管理员、巡检和源文件编辑拆成独立分区，避免把所有运行配置堆在一个页面里。
          </p>
        </div>

        <div class="status-badge max-w-sm text-xs leading-6 text-slate-400">
          高频配置前置，低频配置后置；代理等高级项默认折叠，源文件编辑仍然保留。
        </div>
      </div>

      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <div class="glass-card-soft p-4">
          <div class="text-2xl">🧩</div>
          <div class="mt-3 text-sm font-medium text-white">独立配置分区</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">邮箱服务、同步、代理、安全分别独立，不再混在一张表单里。</div>
        </div>
        <div class="glass-card-soft p-4">
          <div class="text-2xl">☁️</div>
          <div class="mt-3 text-sm font-medium text-white">动态同步配置</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">先选择邮箱提供者 / 启用目标，再按状态展示对应配置。</div>
        </div>
        <div class="glass-card-soft p-4">
          <div class="text-2xl">📝</div>
          <div class="mt-3 text-sm font-medium text-white">源文件编辑保留</div>
          <div class="mt-1 text-xs leading-5 text-slate-400">可视化配置之外，仍可直接维护完整 .env 源文件。</div>
        </div>
      </div>
    </div>

    <div class="glass-card p-4">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="item in visualCategories"
          :key="item.key"
          @click="visualCategory = item.key"
          class="pill-tab flex items-center gap-2"
          :class="visualCategory === item.key
            ? 'pill-tab-active'
            : ''"
        >
          <span class="text-base">{{ item.icon }}</span>
          {{ item.label }}
        </button>
      </div>
    </div>

    <div
      v-if="selectedRuntimeCategory"
      class="glass-card p-6"
    >
      <div class="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
            <span>{{ currentRuntimeCategoryMeta?.icon }}</span>
            {{ currentRuntimeCategoryMeta?.badge }}
          </div>
          <h3 class="section-heading">{{ currentRuntimeCategoryMeta?.title }}</h3>
          <p class="section-subtitle max-w-3xl">
            {{ currentRuntimeCategoryMeta?.description }}
          </p>
          <p
            v-if="currentRuntimeCategoryMeta?.note"
            class="mt-2 text-xs text-slate-500"
          >
            {{ currentRuntimeCategoryMeta.note }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <span
            v-if="runtimeSaved"
            class="status-badge border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
          >
            已保存
          </span>
          <span
            class="status-badge min-w-[84px] justify-center"
            :class="currentRuntimeStatus.class"
          >
            {{ currentRuntimeStatus.label }}
          </span>
        </div>
      </div>

      <div
        v-if="runtimeMessage"
        class="mb-4 rounded-2xl px-4 py-3 text-sm border"
        :class="runtimeMessageClass"
      >
        {{ runtimeMessage }}
      </div>

      <div v-if="runtimeLoading" class="text-sm text-slate-400">
        正在加载当前配置...
      </div>

      <div v-else-if="selectedRuntimeCategory === 'cloudmail'" class="space-y-5">
        <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4 flex items-center justify-between gap-4">
            <div>
              <div class="text-sm font-medium text-white">邮箱提供者</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                先选择当前用于创建临时邮箱、收验证码和自动复用的邮箱后端。
              </div>
            </div>
            <div class="status-badge text-xs text-slate-400">
              {{ mailProviderLabel(selectedMailProvider) }}
            </div>
          </div>
          <select v-model="runtimeForm.MAIL_PROVIDER" class="input-dark">
            <option value="mo_email">Mo Email</option>
            <option value="cloudmail">CloudMail</option>
            <option value="cloudflare_temp_email">Cloudflare Temp Email</option>
          </select>
        </div>

        <div v-if="selectedMailProvider === 'mo_email'" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">Mo Email</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              填写 mo.gymbro.cloud 地址、API Key、邮箱域名和自动命名规则。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in moEmailProviderFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <select
                v-if="field.key === 'MO_EMAIL_DOMAIN' && moEmailDomains.length"
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option v-for="domain in moEmailDomains" :key="domain" :value="domain">
                  {{ domain }}
                </option>
              </select>
              <input
                v-else
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-else-if="selectedMailProvider === 'cloudmail'" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">CloudMail</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              填写 CloudMail API 地址、管理员账号和用于创建临时邮箱的域名。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in cloudmailProviderFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <select
                v-if="isToggleField(field.key)"
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option value="true">启用</option>
                <option value="false">关闭</option>
              </select>
              <input
                v-else
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-else-if="selectedMailProvider === 'cloudflare_temp_email'" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">Cloudflare Temp Email</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              填写 Cloudflare Temp Email 管理端地址、管理员密码和默认邮箱域名。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in cfTempEmailFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <input
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            保存后会立即热加载；后续创建账号、自动收验证码和自动复用都会改用当前选择的邮箱提供者。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else-if="selectedRuntimeCategory === 'sync'" class="space-y-5">
        <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4 flex items-center justify-between gap-4">
            <div>
              <div class="text-sm font-medium text-white">同步目标开关</div>
              <div class="mt-1 text-xs leading-5 text-slate-400">
                可同时启用多个远端。界面只展示当前已启用目标的详细配置。
              </div>
            </div>
            <div class="status-badge text-xs text-slate-400">
              {{ enabledSyncTargetsText }}
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div v-for="field in syncToggleFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
              </label>
              <select
                v-model="runtimeForm[field.key]"
                class="input-dark"
              >
                <option value="true">启用</option>
                <option value="false">关闭</option>
              </select>
            </div>
          </div>
        </div>

        <div v-if="syncCpaEnabled" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">CPA</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              为已启用的 CPA 远端填写连接地址和管理密钥。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in syncCpaFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <input
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-if="syncSub2apiEnabled" class="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div class="mb-4">
            <div class="text-sm font-medium text-white">Sub2API</div>
            <div class="mt-1 text-xs leading-5 text-slate-400">
              为已启用的 Sub2API 远端填写地址、管理员邮箱和密码。
            </div>
          </div>
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="field in syncSub2apiFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
              <label class="mb-2 block text-sm font-medium text-slate-300">
                {{ field.prompt }}
                <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              </label>
              <input
                v-model="runtimeForm[field.key]"
                :type="fieldInputType(field.key)"
                :placeholder="field.default || ''"
                class="input-dark"
              />
            </div>
          </div>
        </div>

        <div v-if="!syncCpaEnabled && !syncSub2apiEnabled" class="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-slate-400">
          当前还没有启用任何远端同步目标。先打开上面的开关，再填写对应远端配置。
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            保存后会立即热加载；账号池操作会根据当前已启用远端决定后续同步行为。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else-if="selectedRuntimeCategory === 'proxy'" class="space-y-5">
        <div class="grid gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
          <nav
            class="rounded-2xl border border-white/10 bg-white/5 p-2"
            aria-label="代理配置菜单"
          >
            <button
              v-for="item in proxyMenuSections"
              :key="item.key"
              type="button"
              @click="proxyMenuSection = item.key"
              :aria-pressed="proxyMenuSection === item.key"
              class="group flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left transition hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              :class="proxyMenuSection === item.key ? 'bg-blue-500/15 text-blue-100' : 'text-slate-300'"
            >
              <span
                class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
                :class="item.dotClass"
              ></span>
              <span class="min-w-0">
                <span class="block text-sm font-medium">{{ item.label }}</span>
                <span class="mt-1 block text-xs leading-5 text-slate-500 group-hover:text-slate-400">
                  {{ item.description }}
                </span>
              </span>
            </button>
          </nav>

          <div class="min-w-0 space-y-4">
            <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div class="text-sm font-medium text-white">{{ currentProxyMenuMeta.label }}</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    {{ currentProxyMenuMeta.longDescription }}
                  </div>
                </div>
                <div class="status-badge text-xs text-slate-400">
                  {{ currentProxyMenuStatus }}
                </div>
              </div>
            </div>

            <div v-if="proxyMenuSection === 'browser'" class="space-y-4">
              <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div class="mb-4">
                  <div class="text-sm font-medium text-white">浏览器显示方式</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    控制 Playwright 自动化浏览器是否弹出窗口。隐藏和内嵌模式都不会弹出独立窗口。
                  </div>
                </div>
                <select
                  v-model="runtimeForm.PLAYWRIGHT_BROWSER_MODE"
                  class="input-dark"
                  @change="syncBrowserModeCompatibility"
                >
                  <option value="hidden">隐藏</option>
                  <option value="embedded">内嵌</option>
                  <option value="visible">可见窗口</option>
                </select>
              </div>

              <div v-if="fieldByKey('BROWSER_PARALLEL_WORKERS')" class="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div class="mb-4">
                  <div class="text-sm font-medium text-white">并行窗口数</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    账号补满、轮转和直注批量任务最多可同时启动 3 个独立浏览器。
                  </div>
                </div>
                <input
                  v-model.number="runtimeForm.BROWSER_PARALLEL_WORKERS"
                  type="number"
                  min="1"
                  max="3"
                  class="input-dark"
                />
              </div>
            </div>

            <div v-else-if="proxyMenuSection === 'outbound'" class="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div class="text-sm font-medium text-white">出口代理池</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    后端访问 OpenAI、邮箱服务、CPA 和 Sub2API 时使用。默认走 Windows Clash。
                  </div>
                </div>
                <div class="status-badge text-xs text-slate-400">
                  {{ outboundProxyEnabled ? '已启用' : '已关闭' }}
                </div>
              </div>
              <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div v-for="field in outboundProxyFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                  <label class="mb-2 block text-sm font-medium text-slate-300">
                    {{ field.prompt }}
                    <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                  </label>
                  <select
                    v-if="isToggleField(field.key)"
                    v-model="runtimeForm[field.key]"
                    class="input-dark"
                  >
                    <option value="true">启用</option>
                    <option value="false">关闭</option>
                  </select>
                  <input
                    v-else
                    v-model="runtimeForm[field.key]"
                    :type="fieldInputType(field.key)"
                    :placeholder="field.default || ''"
                    class="input-dark"
                  />
                </div>
              </div>
            </div>

            <div v-else-if="proxyMenuSection === 'node'" class="space-y-4">
              <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div>
                    <div class="text-sm font-medium text-white">代理节点状态</div>
                    <div class="mt-1 text-xs leading-5 text-slate-400">
                      状态读取和手动刷新使用后端已经保存的配置。改完字段后先保存，再刷新节点。
                    </div>
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      @click="loadProxyNodeStatus"
                      :disabled="proxyNodeLoading"
                      class="btn-secondary"
                    >
                      {{ proxyNodeLoading ? '读取中...' : '读取状态' }}
                    </button>
                    <button
                      type="button"
                      @click="refreshProxyNode"
                      :disabled="proxyNodeRefreshing || !proxyNodeCanRefresh"
                      class="btn-primary"
                    >
                      {{ proxyNodeRefreshing ? '刷新中...' : '刷新节点' }}
                    </button>
                  </div>
                </div>

                <div
                  v-if="proxyNodeMessage"
                  class="mt-4 rounded-2xl border px-4 py-3 text-sm"
                  :class="proxyNodeMessageClass"
                >
                  {{ proxyNodeMessage }}
                </div>

                <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="text-xs text-slate-500">接口状态</div>
                    <div class="mt-2 text-sm font-medium text-white">{{ proxyNodeStatusEnabledText }}</div>
                  </div>
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="text-xs text-slate-500">提供者</div>
                    <div class="mt-2 text-sm font-medium text-white">{{ proxyNodeStatusProviderText }}</div>
                  </div>
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="text-xs text-slate-500">当前出口池</div>
                    <div class="mt-2 break-all font-mono text-xs text-slate-200">{{ proxyNodeOutboundPoolText }}</div>
                  </div>
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="text-xs text-slate-500">最近刷新</div>
                    <div class="mt-2 text-sm font-medium text-white">{{ proxyNodeLastRefreshText }}</div>
                  </div>
                </div>

                <div class="mt-4 grid gap-3 lg:grid-cols-2">
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="mb-2 text-xs text-slate-500">当前节点</div>
                    <div class="break-all font-mono text-xs leading-5 text-slate-200">
                      {{ proxyNodeCurrentText }}
                    </div>
                  </div>
                  <div class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <div class="mb-2 text-xs text-slate-500">刷新结果</div>
                    <div class="break-all font-mono text-xs leading-5 text-slate-200">
                      {{ proxyNodeRefreshResultText }}
                    </div>
                  </div>
                </div>
              </div>

              <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div class="text-sm font-medium text-white">接口连接</div>
                    <div class="mt-1 text-xs leading-5 text-slate-400">
                      选择节点提供者、协议和 API 地址。当前只支持 Webshare。
                    </div>
                  </div>
                  <div class="status-badge text-xs text-slate-400">
                    {{ proxyNodeEnabled ? '已启用' : '已关闭' }}
                  </div>
                </div>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <div v-for="field in proxyNodeConnectionFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <label class="mb-2 block text-sm font-medium text-slate-300">
                      {{ field.prompt }}
                      <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                    </label>
                    <select
                      v-if="field.key === 'PROXY_NODE_PROVIDER'"
                      v-model="runtimeForm[field.key]"
                      class="input-dark"
                    >
                      <option value="none">不使用</option>
                      <option value="webshare">Webshare</option>
                    </select>
                    <select
                      v-else-if="field.key === 'PROXY_NODE_PROTOCOL'"
                      v-model="runtimeForm[field.key]"
                      class="input-dark"
                    >
                      <option value="http">HTTP</option>
                      <option value="socks5">SOCKS5</option>
                      <option value="socks5h">SOCKS5H</option>
                    </select>
                    <select
                      v-else-if="isToggleField(field.key)"
                      v-model="runtimeForm[field.key]"
                      class="input-dark"
                    >
                      <option value="true">启用</option>
                      <option value="false">关闭</option>
                    </select>
                    <input
                      v-else
                      v-model="runtimeForm[field.key]"
                      :type="fieldInputType(field.key)"
                      :placeholder="field.default || ''"
                      class="input-dark"
                    />
                  </div>
                </div>
              </div>

              <div class="rounded-2xl border border-white/10 bg-white/5 p-5">
                <div class="mb-4">
                  <div class="text-sm font-medium text-white">刷新行为</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    设置任务前是否自动刷新、等待新节点的间隔和超时，以及是否写入出口代理池。
                  </div>
                </div>
                <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                  <div v-for="field in proxyNodeRefreshFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                    <label class="mb-2 block text-sm font-medium text-slate-300">
                      {{ field.prompt }}
                      <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                    </label>
                    <select
                      v-if="isToggleField(field.key)"
                      v-model="runtimeForm[field.key]"
                      class="input-dark"
                    >
                      <option value="true">启用</option>
                      <option value="false">关闭</option>
                    </select>
                    <input
                      v-else
                      v-model="runtimeForm[field.key]"
                      :type="fieldInputType(field.key)"
                      :placeholder="field.default || ''"
                      class="input-dark"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div v-else-if="proxyMenuSection === 'advanced'" class="rounded-2xl border border-white/10 bg-white/5 p-4">
              <button
                type="button"
                @click="proxyExpanded = !proxyExpanded"
                :aria-expanded="proxyExpanded"
                aria-controls="proxy-advanced-fields"
                class="flex w-full items-center justify-between gap-4 rounded-xl px-1 py-1 text-left focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                <div>
                  <div class="text-sm font-medium text-white">高级代理设置</div>
                  <div class="mt-1 text-xs leading-5 text-slate-400">
                    只有浏览器流量需要覆盖出口代理池时才填写。默认保持折叠，避免误改。
                  </div>
                </div>
                <span class="text-xs text-slate-400">{{ proxyExpanded ? '收起' : '展开' }}</span>
              </button>

              <div
                v-if="proxyExpanded"
                id="proxy-advanced-fields"
                class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
              >
                <div v-for="field in proxyFields" :key="field.key" class="rounded-2xl border border-white/10 bg-slate-950/25 p-4">
                  <label class="mb-2 block text-sm font-medium text-slate-300">
                    {{ field.prompt }}
                    <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
                  </label>
                  <input
                    v-model="runtimeForm[field.key]"
                    :type="fieldInputType(field.key)"
                    :placeholder="field.default || ''"
                    class="input-dark"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            保存后会影响后续任务。正在运行的任务会继续使用启动时选中的代理。
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>

      <div v-else class="space-y-4">
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="field in currentRuntimeFields" :key="field.key" class="rounded-2xl border border-white/10 bg-white/5 p-4">
            <label class="mb-2 block text-sm font-medium text-slate-300">
              {{ field.prompt }}
              <span v-if="isRuntimeRequired(field)" class="text-red-400">*</span>
              <span v-if="field.key === 'API_KEY'" class="ml-1 text-xs text-slate-500">（留空自动生成）</span>
            </label>
            <input
              v-model="runtimeForm[field.key]"
              :type="fieldInputType(field.key)"
              :placeholder="field.default || ''"
              class="input-dark"
            />
          </div>
        </div>

        <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
          <p class="text-xs leading-6 text-slate-400">
            {{ currentRuntimeCategoryMeta?.footer }}
          </p>
          <button
            @click="saveRuntimeConfig"
            :disabled="runtimeSaving || runtimeLoading"
            class="btn-primary"
          >
            {{ runtimeSaving ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>
    </div>

    <Settings
      v-else-if="visualCategory === 'admin'"
      :admin-status="adminStatus"
      :codex-status="codexStatus"
      section="admin"
      @refresh="$emit('refresh')"
      @admin-progress="$emit('admin-progress')"
    />

    <Settings
      v-else-if="visualCategory === 'auto-check'"
      :admin-status="adminStatus"
      :codex-status="codexStatus"
      section="auto-check"
      @refresh="$emit('refresh')"
      @admin-progress="$emit('admin-progress')"
    />

    <div v-else-if="visualCategory === 'source'" class="glass-card space-y-4 p-6">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="mb-2 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">
            <span>📝</span>
            Source Editor
          </div>
          <h3 class="section-heading">源文件编辑</h3>
          <p class="section-subtitle">
            直接编辑 .env 源文件。保存后会立即重载并校验邮箱服务 / 远端同步配置。
          </p>
        </div>
        <div class="status-badge break-all font-mono text-[11px] text-slate-400">
          {{ sourcePath || '.env' }}
        </div>
      </div>

      <div
        v-if="sourceMessage"
        class="rounded-2xl px-4 py-3 text-sm border"
        :class="sourceMessageClass"
      >
        {{ sourceMessage }}
      </div>

      <textarea
        v-model="sourceContent"
        rows="20"
        spellcheck="false"
        class="textarea-dark min-h-[420px] font-mono"
        placeholder="在这里编辑 .env 内容"
      />

      <div class="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 lg:flex-row lg:items-center lg:justify-between">
        <p class="text-xs leading-6 text-slate-400">
          这里是原始文本模式，适合你直接粘贴或手工维护完整 .env。
        </p>
        <div class="flex gap-2">
          <button
            @click="loadSourceConfig"
            :disabled="sourceLoading || sourceSaving"
            class="btn-secondary"
          >
            {{ sourceLoading ? '加载中...' : '重新读取' }}
          </button>
          <button
            @click="saveSourceConfig"
            :disabled="sourceLoading || sourceSaving"
            class="btn-primary"
          >
            {{ sourceSaving ? '保存中...' : '保存源文件' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, setApiKey } from '../api.js'
import Settings from './Settings.vue'

defineProps({
  adminStatus: {
    type: Object,
    default: null,
  },
  codexStatus: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh', 'admin-progress'])

const runtimeCategoryKeys = {
  cloudmail: ['MAIL_PROVIDER', 'MO_EMAIL_BASE_URL', 'MO_EMAIL_API_KEY', 'MO_EMAIL_DOMAIN', 'MO_EMAIL_NAME_PREFIX', 'MO_EMAIL_START_INDEX', 'MO_EMAIL_EXPIRY_TIME', 'CLOUDMAIL_BASE_URL', 'CLOUDMAIL_EMAIL', 'CLOUDMAIL_PASSWORD', 'CLOUDMAIL_DOMAIN', 'CF_TEMP_EMAIL_BASE_URL', 'CF_TEMP_EMAIL_ADMIN_PASSWORD', 'CF_TEMP_EMAIL_DOMAIN'],
  sync: ['SYNC_TARGET_CPA', 'SYNC_TARGET_SUB2API', 'CPA_URL', 'CPA_KEY', 'SUB2API_URL', 'SUB2API_EMAIL', 'SUB2API_PASSWORD', 'SUB2API_GROUP'],
  proxy: ['PLAYWRIGHT_BROWSER_MODE', 'PLAYWRIGHT_HEADLESS', 'BROWSER_PARALLEL_WORKERS', 'OUTBOUND_PROXY_ENABLED', 'OUTBOUND_PROXY_POOL', 'OUTBOUND_PROXY_BYPASS', 'OUTBOUND_PROXY_STRATEGY', 'OUTBOUND_PROXY_FAILOVER', 'PROXY_NODE_ENABLED', 'PROXY_NODE_PROVIDER', 'PROXY_NODE_API_KEY', 'PROXY_NODE_BASE_URL', 'PROXY_NODE_PROTOCOL', 'PROXY_NODE_AUTO_REFRESH', 'PROXY_NODE_REFRESH_BEFORE_TASK', 'PROXY_NODE_POLL_INTERVAL_SECONDS', 'PROXY_NODE_POLL_TIMEOUT_SECONDS', 'PROXY_NODE_COUNTRY', 'PROXY_NODE_APPLY_TO_OUTBOUND_POOL', 'PLAYWRIGHT_PROXY_URL', 'PLAYWRIGHT_PROXY_BYPASS'],
  security: ['API_KEY'],
}

const runtimeCategoryMeta = {
  cloudmail: {
    icon: '📧',
    badge: 'Mail Provider',
    title: '邮箱服务配置',
    description: '配置自动注册和收验证码所需的邮箱后端。可以在 Mo Email、CloudMail 和 Cloudflare Temp Email 之间切换。',
    note: '带 * 的项会直接影响账号池操作；只有当前选中的邮箱提供者配置会被视为运行时必填。',
    footer: '邮箱提供者配置保存后会立即热加载；之后的注册、复用和验证码轮询会直接使用新配置。',
  },
  sync: {
    icon: '☁️',
    badge: 'Remote Sync',
    title: '远端同步',
    description: '先选择启用的远端同步目标，再填写对应的连接信息。账号池操作会根据这里的启用状态决定同步到哪些远端。',
    note: '支持同时启用 CPA 和 Sub2API；界面只显示当前已启用目标的详细配置。',
  },
  proxy: {
    icon: '🛰️',
    badge: 'Proxy / Advanced',
    title: '代理 / 高级',
    description: '用于配置后端出口代理池、浏览器显示方式和 Playwright 覆盖代理。',
    note: '出口代理池默认使用 Windows Clash；Playwright 代理留空时跟随出口代理池。',
  },
  security: {
    icon: '🔐',
    badge: 'Security',
    title: '安全 / 访问控制',
    description: '入口级配置集中放在这里。API Key 决定 Web 面板和 HTTP API 的访问控制，不再和其他运行参数混在一起。',
    note: '留空会自动生成新的 API Key；保存后前端会立即切换到新的密钥。',
    footer: '这是控制面板和 API 的入口密钥。修改后会立即生效，并同步刷新当前浏览器里的 API Key。',
  },
}

const visualCategories = [
  { key: 'cloudmail', label: '邮箱服务', icon: '📧' },
  { key: 'sync', label: '远端同步', icon: '☁️' },
  { key: 'proxy', label: '代理 / 高级', icon: '🛰️' },
  { key: 'security', label: '安全 / 访问控制', icon: '🔐' },
  { key: 'admin', label: '管理员 / 主号', icon: '👤' },
  { key: 'auto-check', label: '巡检设置', icon: '🔄' },
  { key: 'source', label: '源文件编辑', icon: '📝' },
]

const visualCategory = ref('cloudmail')
const proxyExpanded = ref(false)
const proxyMenuSection = ref('browser')

const runtimeFields = ref([])
const runtimeForm = reactive({})
const moEmailDomains = ref([])
const runtimeLoading = ref(false)
const runtimeSaving = ref(false)
const runtimeSaved = ref(false)
const runtimeMessage = ref('')
const runtimeMessageClass = ref('')
const proxyNodeStatus = ref(null)
const proxyNodeLoading = ref(false)
const proxyNodeRefreshing = ref(false)
const proxyNodeMessage = ref('')
const proxyNodeMessageClass = ref('')

const sourcePath = ref('')
const sourceContent = ref('')
const sourceLoading = ref(false)
const sourceSaving = ref(false)
const sourceLoaded = ref(false)
const sourceMessage = ref('')
const sourceMessageClass = ref('')
const runtimeRequiredKeys = new Set(['API_KEY'])

const selectedRuntimeCategory = computed(() => runtimeCategoryKeys[visualCategory.value] ? visualCategory.value : '')
const currentRuntimeCategoryMeta = computed(() => runtimeCategoryMeta[selectedRuntimeCategory.value] || null)

function fieldByKey(key) {
  return runtimeFields.value.find(field => field.key === key) || null
}

function fieldsByKeys(keys) {
  return keys
    .map(key => fieldByKey(key))
    .filter(Boolean)
}

const securityFields = computed(() => fieldsByKeys(runtimeCategoryKeys.security))
const outboundProxyFields = computed(() => fieldsByKeys(['OUTBOUND_PROXY_ENABLED', 'OUTBOUND_PROXY_POOL', 'OUTBOUND_PROXY_BYPASS', 'OUTBOUND_PROXY_STRATEGY', 'OUTBOUND_PROXY_FAILOVER']))
const proxyNodeConnectionFields = computed(() => fieldsByKeys(['PROXY_NODE_ENABLED', 'PROXY_NODE_PROVIDER', 'PROXY_NODE_PROTOCOL', 'PROXY_NODE_BASE_URL', 'PROXY_NODE_API_KEY']))
const proxyNodeRefreshFields = computed(() => fieldsByKeys(['PROXY_NODE_AUTO_REFRESH', 'PROXY_NODE_REFRESH_BEFORE_TASK', 'PROXY_NODE_POLL_INTERVAL_SECONDS', 'PROXY_NODE_POLL_TIMEOUT_SECONDS', 'PROXY_NODE_COUNTRY', 'PROXY_NODE_APPLY_TO_OUTBOUND_POOL']))
const proxyFields = computed(() => fieldsByKeys(['PLAYWRIGHT_PROXY_URL', 'PLAYWRIGHT_PROXY_BYPASS']))
const syncToggleFields = computed(() => fieldsByKeys(['SYNC_TARGET_CPA', 'SYNC_TARGET_SUB2API']))
const selectedMailProvider = computed(() => {
  const value = String(runtimeForm.MAIL_PROVIDER || 'mo_email').toLowerCase()
  return ['mo_email', 'cloudmail', 'cloudflare_temp_email'].includes(value) ? value : 'mo_email'
})
const moEmailProviderFields = computed(() => fieldsByKeys(['MO_EMAIL_BASE_URL', 'MO_EMAIL_API_KEY', 'MO_EMAIL_DOMAIN', 'MO_EMAIL_NAME_PREFIX', 'MO_EMAIL_START_INDEX', 'MO_EMAIL_EXPIRY_TIME']))
const cloudmailProviderFields = computed(() => fieldsByKeys(['CLOUDMAIL_BASE_URL', 'CLOUDMAIL_EMAIL', 'CLOUDMAIL_PASSWORD', 'CLOUDMAIL_DOMAIN']))
const cfTempEmailFields = computed(() => fieldsByKeys(['CF_TEMP_EMAIL_BASE_URL', 'CF_TEMP_EMAIL_ADMIN_PASSWORD', 'CF_TEMP_EMAIL_DOMAIN']))

const syncCpaEnabled = computed(() => String(runtimeForm.SYNC_TARGET_CPA || '').toLowerCase() === 'true')
const syncSub2apiEnabled = computed(() => String(runtimeForm.SYNC_TARGET_SUB2API || '').toLowerCase() === 'true')
const outboundProxyEnabled = computed(() => String(runtimeForm.OUTBOUND_PROXY_ENABLED || 'true').toLowerCase() === 'true')
const proxyNodeEnabled = computed(() => String(runtimeForm.PROXY_NODE_ENABLED || 'false').toLowerCase() === 'true')
const proxyNodeProvider = computed(() => String(runtimeForm.PROXY_NODE_PROVIDER || 'none').toLowerCase())
const proxyNodeCanRefresh = computed(() => proxyNodeEnabled.value && proxyNodeProvider.value === 'webshare' && !runtimeLoading.value)
const syncCpaFields = computed(() => syncCpaEnabled.value ? fieldsByKeys(['CPA_URL', 'CPA_KEY']) : [])
const syncSub2apiFields = computed(() => syncSub2apiEnabled.value ? fieldsByKeys(['SUB2API_URL', 'SUB2API_EMAIL', 'SUB2API_PASSWORD', 'SUB2API_GROUP']) : [])

const proxyMenuSections = [
  {
    key: 'browser',
    label: '浏览器',
    description: '显示方式和并行窗口',
    longDescription: '控制自动化浏览器是否显示，以及批量任务允许的浏览器窗口数。',
    dotClass: 'bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.75)]',
  },
  {
    key: 'outbound',
    label: '出口代理池',
    description: '后端外部请求出口',
    longDescription: '设置后端访问 OpenAI、邮箱服务和远端同步服务时使用的代理池。',
    dotClass: 'bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.75)]',
  },
  {
    key: 'node',
    label: '节点接口',
    description: 'Webshare 刷新和状态',
    longDescription: '配置代理节点接口，查看当前节点，并手动刷新后写入出口代理池。',
    dotClass: 'bg-blue-400 shadow-[0_0_12px_rgba(96,165,250,0.75)]',
  },
  {
    key: 'advanced',
    label: '高级覆盖',
    description: 'Playwright 专用代理',
    longDescription: '仅在浏览器流量需要覆盖全局出口代理池时使用。',
    dotClass: 'bg-amber-400 shadow-[0_0_12px_rgba(251,191,36,0.75)]',
  },
]

const currentProxyMenuMeta = computed(() => proxyMenuSections.find(item => item.key === proxyMenuSection.value) || proxyMenuSections[0])

const currentProxyMenuStatus = computed(() => {
  if (proxyMenuSection.value === 'browser') {
    return normalizedBrowserMode.value === 'visible'
      ? '可见窗口'
      : normalizedBrowserMode.value === 'embedded'
        ? '内嵌'
        : '隐藏'
  }
  if (proxyMenuSection.value === 'outbound') {
    return outboundProxyEnabled.value ? '出口代理已启用' : '出口代理已关闭'
  }
  if (proxyMenuSection.value === 'node') {
    if (!proxyNodeEnabled.value || proxyNodeProvider.value === 'none') {
      return '节点接口未启用'
    }
    return proxyNodeProvider.value === 'webshare' ? 'Webshare' : proxyNodeProvider.value
  }
  return fieldsByKeys(['PLAYWRIGHT_PROXY_URL', 'PLAYWRIGHT_PROXY_BYPASS']).some(field => field.configured)
    ? '已设置覆盖'
    : '未设置覆盖'
})

const proxyNodeStatusEnabledText = computed(() => {
  const status = proxyNodeStatus.value
  if (!status) {
    return proxyNodeEnabled.value ? '表单已启用，未读取后端状态' : '未启用'
  }
  return status.enabled ? '后端已启用' : '后端未启用'
})

const proxyNodeStatusProviderText = computed(() => {
  const status = proxyNodeStatus.value
  return status?.provider || proxyNodeProvider.value || 'none'
})

const proxyNodeOutboundPoolText = computed(() => {
  const status = proxyNodeStatus.value
  return status?.outbound_proxy_pool || runtimeForm.OUTBOUND_PROXY_POOL || '未设置'
})

const proxyNodeLastRefreshText = computed(() => {
  const refresh = proxyNodeStatus.value?.last_refresh
  if (!refresh || Object.keys(refresh).length === 0) {
    return '暂无记录'
  }
  if (refresh.refreshed_at) {
    return formatUnixTime(refresh.refreshed_at)
  }
  if (refresh.message) {
    return refresh.message
  }
  return '已有记录'
})

const proxyNodeCurrentText = computed(() => {
  const current = proxyNodeStatus.value?.current
  if (!current || Object.keys(current).length === 0) {
    return proxyNodeLoading.value ? '正在读取...' : '暂无当前节点'
  }
  if (current.error) {
    return current.error
  }
  if (current.proxy_url) {
    return current.proxy_url
  }
  return compactJson(current.node || current)
})

const proxyNodeRefreshResultText = computed(() => {
  const refresh = proxyNodeStatus.value?.last_refresh
  if (!refresh || Object.keys(refresh).length === 0) {
    return '暂无刷新结果'
  }
  if (refresh.proxy_url) {
    return `${refresh.proxy_url}${refresh.applied ? '，已写入出口代理池' : '，未写入出口代理池'}`
  }
  if (refresh.message) {
    return refresh.message
  }
  return compactJson(refresh)
})

const currentRuntimeFields = computed(() => {
  if (selectedRuntimeCategory.value === 'cloudmail') {
    if (selectedMailProvider.value === 'mo_email') {
      return moEmailProviderFields.value
    }
    if (selectedMailProvider.value === 'cloudflare_temp_email') {
      return cfTempEmailFields.value
    }
    return cloudmailProviderFields.value
  }
  if (selectedRuntimeCategory.value === 'security') {
    return securityFields.value
  }
  return []
})

const enabledSyncTargetsText = computed(() => {
  const targets = []
  if (syncCpaEnabled.value) {
    targets.push('CPA')
  }
  if (syncSub2apiEnabled.value) {
    targets.push('Sub2API')
  }
  return targets.length ? `已启用：${targets.join(' + ')}` : '当前未启用远端'
})

const currentRuntimeStatus = computed(() => {
  if (!selectedRuntimeCategory.value) {
    return {
      label: '',
      class: 'border-white/10 bg-white/5 text-slate-400',
    }
  }

  if (selectedRuntimeCategory.value === 'sync') {
    if (!syncCpaEnabled.value && !syncSub2apiEnabled.value) {
      return {
        label: '未启用',
        class: 'border-white/10 bg-white/5 text-slate-400',
      }
    }

    const cpaReady = !syncCpaEnabled.value || syncCpaFields.value.every(field => field.configured)
    const sub2apiReady = !syncSub2apiEnabled.value || syncSub2apiFields.value.every(field => field.configured)

    return cpaReady && sub2apiReady
      ? {
          label: '已配置',
          class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        }
      : {
          label: '未配置',
          class: 'border-red-400/20 bg-red-500/10 text-red-200',
        }
  }

  if (selectedRuntimeCategory.value === 'proxy') {
    const proxyConfigured = outboundProxyEnabled.value || fieldsByKeys(['PLAYWRIGHT_PROXY_URL', 'PLAYWRIGHT_PROXY_BYPASS']).some(field => field.configured)
    const browserMode = normalizedBrowserMode.value
    if (proxyConfigured) {
      return {
        label: '已设置',
        class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
      }
    }
    return browserMode === 'visible'
      ? {
          label: '可见窗口',
          class: 'border-amber-400/20 bg-amber-500/10 text-amber-200',
        }
      : browserMode === 'embedded'
        ? {
            label: '内嵌',
            class: 'border-cyan-400/20 bg-cyan-500/10 text-cyan-200',
          }
      : {
          label: '隐藏',
          class: 'border-white/10 bg-white/5 text-slate-400',
        }
  }

  if (selectedRuntimeCategory.value === 'cloudmail') {
    const providerFields = selectedMailProvider.value === 'mo_email'
      ? moEmailProviderFields.value
      : selectedMailProvider.value === 'cloudflare_temp_email'
        ? cfTempEmailFields.value
        : cloudmailProviderFields.value
    const configured = providerFields.length > 0 && providerFields.every(field => !isRuntimeRequired(field) || field.configured)
    return configured
      ? {
          label: '已配置',
          class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
        }
      : {
          label: '未配置',
          class: 'border-red-400/20 bg-red-500/10 text-red-200',
        }
  }

  const fields = currentRuntimeFields.value
  const configured = fields.length > 0 && fields.every(field => !isRuntimeRequired(field) || field.configured)

  return configured
    ? {
        label: '已配置',
        class: 'border-emerald-400/20 bg-emerald-500/10 text-emerald-200',
      }
    : {
        label: '未配置',
        class: 'border-red-400/20 bg-red-500/10 text-red-200',
      }
})

function mailProviderLabel(provider) {
  if (provider === 'mo_email') return 'Mo Email'
  if (provider === 'cloudflare_temp_email') return 'Cloudflare Temp Email'
  return 'CloudMail'
}

function setRuntimeMessage(text, type = 'success') {
  runtimeMessage.value = text
  runtimeMessageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setRuntimeMessage._timer)
  setRuntimeMessage._timer = window.setTimeout(() => {
    runtimeMessage.value = ''
  }, 8000)
}

function setSourceMessage(text, type = 'success') {
  sourceMessage.value = text
  sourceMessageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setSourceMessage._timer)
  setSourceMessage._timer = window.setTimeout(() => {
    sourceMessage.value = ''
  }, 8000)
}

function setProxyNodeMessage(text, type = 'success') {
  proxyNodeMessage.value = text
  proxyNodeMessageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setProxyNodeMessage._timer)
  setProxyNodeMessage._timer = window.setTimeout(() => {
    proxyNodeMessage.value = ''
  }, 8000)
}

function fieldInputType(key) {
  return key.includes('PASSWORD') || key.includes('KEY') ? 'password' : 'text'
}

function compactJson(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value || '')
  }
}

function formatUnixTime(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return '时间未知'
  }
  return new Date(numeric * 1000).toLocaleString('zh-CN', { hour12: false })
}

function isToggleField(key) {
  return key === 'SYNC_TARGET_CPA'
    || key === 'SYNC_TARGET_SUB2API'
    || key === 'PLAYWRIGHT_HEADLESS'
    || key === 'OUTBOUND_PROXY_ENABLED'
    || key === 'OUTBOUND_PROXY_FAILOVER'
    || key === 'PROXY_NODE_ENABLED'
    || key === 'PROXY_NODE_AUTO_REFRESH'
    || key === 'PROXY_NODE_REFRESH_BEFORE_TASK'
    || key === 'PROXY_NODE_APPLY_TO_OUTBOUND_POOL'
}

const normalizedBrowserMode = computed(() => {
  const mode = String(runtimeForm.PLAYWRIGHT_BROWSER_MODE || '').toLowerCase()
  if (['hidden', 'visible', 'embedded'].includes(mode)) {
    return mode
  }
  return String(runtimeForm.PLAYWRIGHT_HEADLESS || 'true').toLowerCase() === 'false' ? 'visible' : 'hidden'
})

function syncBrowserModeCompatibility() {
  const mode = normalizedBrowserMode.value
  runtimeForm.PLAYWRIGHT_BROWSER_MODE = mode
  runtimeForm.PLAYWRIGHT_HEADLESS = mode === 'visible' ? 'false' : 'true'
}

function isRuntimeRequired(field) {
  return Boolean(field?.runtime_required) || runtimeRequiredKeys.has(field?.key)
}

function normalizeRuntimeFieldValue(field) {
  const value = field?.value ?? field?.default ?? ''
  if (field?.key === 'PLAYWRIGHT_BROWSER_MODE') {
    const mode = String(value).toLowerCase()
    return ['hidden', 'visible', 'embedded'].includes(mode) ? mode : 'hidden'
  }
  if (isToggleField(field?.key)) {
    return String(value).toLowerCase() === 'true' ? 'true' : 'false'
  }
  return value
}

async function loadRuntimeConfig() {
  runtimeLoading.value = true
  try {
    const result = await api.getRuntimeConfig()
    runtimeFields.value = result.fields || []

    for (const key of Object.keys(runtimeForm)) {
      if (!runtimeFields.value.find(field => field.key === key)) {
        delete runtimeForm[key]
      }
    }
    for (const field of runtimeFields.value) {
      runtimeForm[field.key] = normalizeRuntimeFieldValue(field)
    }
    syncBrowserModeCompatibility()
    if (selectedMailProvider.value === 'mo_email') {
      await loadMoEmailDomains()
    }
  } catch (e) {
    console.error('加载运行时配置失败:', e)
    setRuntimeMessage('加载运行时配置失败: ' + e.message, 'error')
  } finally {
    runtimeLoading.value = false
  }
}

async function loadMoEmailDomains() {
  try {
    const result = await api.getMoEmailDomains()
    moEmailDomains.value = Array.isArray(result.domains) ? result.domains : []
    if (!runtimeForm.MO_EMAIL_DOMAIN && moEmailDomains.value.length) {
      runtimeForm.MO_EMAIL_DOMAIN = moEmailDomains.value[0]
    }
  } catch (e) {
    moEmailDomains.value = []
  }
}

async function loadProxyNodeStatus() {
  proxyNodeLoading.value = true
  try {
    proxyNodeStatus.value = await api.getProxyNodeStatus()
  } catch (e) {
    setProxyNodeMessage('读取代理节点状态失败: ' + e.message, 'error')
  } finally {
    proxyNodeLoading.value = false
  }
}

async function refreshProxyNode() {
  proxyNodeRefreshing.value = true
  try {
    const result = await api.refreshProxyNode()
    proxyNodeStatus.value = {
      ...(proxyNodeStatus.value || {}),
      enabled: result.enabled,
      provider: result.provider,
      protocol: result.protocol,
      outbound_proxy_pool: result.proxy_url || proxyNodeStatus.value?.outbound_proxy_pool || runtimeForm.OUTBOUND_PROXY_POOL || '',
      current: result.node ? { provider: result.provider, proxy_url: result.proxy_url, node: result.node } : proxyNodeStatus.value?.current || {},
      last_refresh: result,
    }
    setProxyNodeMessage(result.proxy_url ? '代理节点已刷新' : (result.message || '代理节点刷新完成'))
    await Promise.all([loadProxyNodeStatus(), loadRuntimeConfig()])
  } catch (e) {
    setProxyNodeMessage(e.message, 'error')
  } finally {
    proxyNodeRefreshing.value = false
  }
}

async function saveRuntimeConfig() {
  runtimeSaving.value = true
  runtimeSaved.value = false
  try {
    const payload = {}
    syncBrowserModeCompatibility()
    for (const field of runtimeFields.value) {
      const raw = runtimeForm[field.key] ?? ''
      payload[field.key] = typeof raw === 'string' ? raw : String(raw)
    }
    const result = await api.saveRuntimeConfig(payload)
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    setRuntimeMessage(result.message || '配置保存成功')
    runtimeSaved.value = true
    window.setTimeout(() => {
      runtimeSaved.value = false
    }, 3000)
    await loadRuntimeConfig()
    emit('refresh')
  } catch (e) {
    setRuntimeMessage(e.message, 'error')
  } finally {
    runtimeSaving.value = false
  }
}

async function loadSourceConfig() {
  sourceLoading.value = true
  try {
    const result = await api.getRuntimeConfigSource()
    sourcePath.value = result.path || '.env'
    sourceContent.value = result.content || ''
    sourceLoaded.value = true
  } catch (e) {
    console.error('加载源文件失败:', e)
    setSourceMessage('加载源文件失败: ' + e.message, 'error')
  } finally {
    sourceLoading.value = false
  }
}

async function saveSourceConfig() {
  sourceSaving.value = true
  try {
    const result = await api.saveRuntimeConfigSource({ content: sourceContent.value })
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    setSourceMessage(result.message || '源文件保存成功')
    await Promise.all([loadSourceConfig(), loadRuntimeConfig()])
    emit('refresh')
  } catch (e) {
    setSourceMessage(e.message, 'error')
  } finally {
    sourceSaving.value = false
  }
}

watch(visualCategory, async (next) => {
  if (next === 'source' && !sourceLoaded.value) {
    await loadSourceConfig()
  }
  if (next === 'proxy' && proxyMenuSection.value === 'node') {
    await loadProxyNodeStatus()
  }
})

watch(proxyMenuSection, async (next) => {
  if (visualCategory.value === 'proxy' && next === 'node') {
    await loadProxyNodeStatus()
  }
})

watch(selectedMailProvider, async (next) => {
  if (next === 'mo_email' && moEmailDomains.value.length === 0) {
    await loadMoEmailDomains()
  }
})

onMounted(async () => {
  await loadRuntimeConfig()
})
</script>
