const BASE = '/api'

function getApiKey() {
  return localStorage.getItem('autoteam_api_key') || ''
}

export function setApiKey(key) {
  localStorage.setItem('autoteam_api_key', key)
}

export function clearApiKey() {
  localStorage.removeItem('autoteam_api_key')
}

async function request(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' }
  const key = getApiKey()
  if (key) {
    headers['Authorization'] = `Bearer ${key}`
  }
  const opts = { method, headers }
  if (body) opts.body = JSON.stringify(body)
  const resp = await fetch(`${BASE}${path}`, opts)
  let data
  try {
    data = await resp.json()
  } catch {
    const err = new Error(`HTTP ${resp.status}: 服务器返回了非 JSON 响应`)
    err.status = resp.status
    throw err
  }
  if (!resp.ok) {
    const msg = formatApiErrorMessage(data, resp.status)
    const err = new Error(msg)
    err.status = resp.status
    throw err
  }
  return data
}

function formatValidationItem(item) {
  if (!item) return ''
  if (typeof item === 'string') return item
  if (typeof item !== 'object') return String(item)
  const msg = item.msg || item.message || ''
  const loc = Array.isArray(item.loc) ? item.loc.join('.') : item.loc
  if (msg && loc) return `${loc}: ${msg}`
  if (msg) return msg
  return JSON.stringify(item)
}

function formatApiErrorMessage(data, status) {
  if (!data) return `HTTP ${status}`
  if (typeof data === 'string') return data
  if (typeof data !== 'object') return String(data)

  if (typeof data.message === 'string' && data.message.trim()) {
    return data.message
  }

  const detail = data.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const parts = detail.map(formatValidationItem).filter(Boolean)
    if (parts.length) {
      return parts.join('；')
    }
  }
  if (detail && typeof detail === 'object') {
    const objectMessage = formatValidationItem(detail)
    if (objectMessage) {
      return objectMessage
    }
  }

  return `HTTP ${status}`
}

export const api = {
  checkAuth: () => request('GET', '/auth/check'),
  getSetupStatus: () => request('GET', '/setup/status'),
  saveSetup: (config) => request('POST', '/setup/save', config),
  getRuntimeConfig: () => request('GET', '/config/runtime'),
  saveRuntimeConfig: (config) => request('PUT', '/config/runtime', config),
  getRuntimeConfigSource: () => request('GET', '/config/source'),
  saveRuntimeConfigSource: (payload) => request('PUT', '/config/source', payload),
  getMoEmailDomains: () => request('GET', '/mail/mo-email/domains'),
  getProxyNodeStatus: () => request('GET', '/proxy-nodes/status'),
  refreshProxyNode: () => request('POST', '/proxy-nodes/refresh'),

  getStatus: ({ realtimeQuota = false } = {}) => request('GET', `/status?realtime_quota=${realtimeQuota ? 'true' : 'false'}`),
  getAdminStatus: () => request('GET', '/admin/status'),
  getMainCodexStatus: () => request('GET', '/main-codex/status'),
  getManualAccountStatus: () => request('GET', '/manual-account/status'),
  getAccounts: () => request('GET', '/accounts'),
  getActiveAccounts: () => request('GET', '/accounts/active'),
  getStandbyAccounts: () => request('GET', '/accounts/standby'),
  deleteAccount: (email) => request('DELETE', `/accounts/${encodeURIComponent(email)}`),
  loginAccount: (email) => request('POST', '/accounts/login', { email }),
  getCodexAuth: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/codex-auth`),
  kickAccount: (email) => request('POST', `/accounts/${encodeURIComponent(email)}/kick`),
  sellAccount: (email) => request('POST', `/accounts/${encodeURIComponent(email)}/sell`),
  bulkAccountAction: (payload) => request('POST', '/accounts/bulk-action', payload),
  listAccounts: ({ category, q, page, page_size, sort } = {}) => {
    const params = new URLSearchParams()
    if (category) params.set('category', category)
    if (q) params.set('q', q)
    if (page != null) params.set('page', String(page))
    if (page_size != null) params.set('page_size', String(page_size))
    if (sort) params.set('sort', sort)
    const qs = params.toString()
    return request('GET', `/accounts${qs ? '?' + qs : ''}`)
  },
  getAccountDetail: (email) => request('GET', `/accounts/${encodeURIComponent(email)}`),
  postAccountsCleanDryRun: () => request('POST', '/accounts/clean/dry-run'),
  postAccountsCleanApply: () => request('POST', '/accounts/clean/apply'),
  allocateAccount: (email, body = {}) => request('POST', `/accounts/${encodeURIComponent(email)}/allocate`, body),
  releaseAccount: (email, body = {}) => request('POST', `/accounts/${encodeURIComponent(email)}/release`, body),
  markAccountInvalid: (email, body) => request('POST', `/accounts/${encodeURIComponent(email)}/mark-invalid`, body),
  repairAccountOauth: (email, body = {}) => request('POST', `/accounts/${encodeURIComponent(email)}/repair-oauth`, body),
  getCpaFiles: () => request('GET', '/cpa/files'),
  startAccountCpaAuth: (email) => request('POST', `/accounts/${encodeURIComponent(email)}/cpa-auth`),

  getAuthsStats: () => request('GET', '/auths/stats'),
  getAuthsAccounts: ({ category, plan_type, q, has_oauth, has_session, page, page_size, sort } = {}) => {
    const params = new URLSearchParams()
    if (category) params.set('category', category)
    if (plan_type) params.set('plan_type', plan_type)
    if (q) params.set('q', q)
    if (has_oauth != null) params.set('has_oauth', has_oauth ? 'true' : 'false')
    if (has_session != null) params.set('has_session', has_session ? 'true' : 'false')
    if (page != null) params.set('page', String(page))
    if (page_size != null) params.set('page_size', String(page_size))
    if (sort) params.set('sort', sort)
    const qs = params.toString()
    return request('GET', `/auths/accounts${qs ? '?' + qs : ''}`)
  },

  startAdminLogin: (email) => request('POST', '/admin/login/start', { email }),
  submitAdminSession: (email, sessionToken) => request('POST', '/admin/login/session', { email, session_token: sessionToken }),
  submitAdminPassword: (password) => request('POST', '/admin/login/password', { password }),
  submitAdminCode: (code) => request('POST', '/admin/login/code', { code }),
  submitAdminWorkspace: (optionId) => request('POST', '/admin/login/workspace', { option_id: optionId }),
  cancelAdminLogin: () => request('POST', '/admin/login/cancel'),
  logoutAdmin: () => request('POST', '/admin/logout'),
  startMainCodexLogin: () => request('POST', '/main-codex/login'),
  startMainCodexSync: () => request('POST', '/main-codex/start'),
  submitMainCodexPassword: (password) => request('POST', '/main-codex/password', { password }),
  submitMainCodexCode: (code) => request('POST', '/main-codex/code', { code }),
  cancelMainCodexSync: () => request('POST', '/main-codex/cancel'),
  deleteMainCodexFromCpa: () => request('POST', '/main-codex/delete-cpa'),
  startManualAccount: () => request('POST', '/manual-account/start'),
  submitManualAccountCallback: (redirectUrl) => request('POST', '/manual-account/callback', { redirect_url: redirectUrl }),
  cancelManualAccount: () => request('POST', '/manual-account/cancel'),

  postSync: () => request('POST', '/sync'),
  postSyncCpa: () => request('POST', '/sync/cpa'),
  postSyncSub2api: () => request('POST', '/sync/sub2api'),
  postSyncFromCpa: () => request('POST', '/sync/from-cpa'),
  postSyncAccounts: () => request('POST', '/sync/accounts'),
  postSyncMainCodex: () => request('POST', '/sync/main-codex'),
  postSyncSavedMainCodex: () => request('POST', '/sync/main-codex/saved'),

  startRotate: (target = null, parallelWorkers = null) => request('POST', '/tasks/rotate', {
    ...(target == null ? {} : { target }),
    ...(parallelWorkers == null ? {} : { parallel_workers: parallelWorkers }),
  }),
  startCheck: () => request('POST', '/tasks/check'),
  startAdd: () => request('POST', '/tasks/add'),
  startFill: (target = null, parallelWorkers = null) => request('POST', '/tasks/fill', {
    ...(target == null ? {} : { target }),
    ...(parallelWorkers == null ? {} : { parallel_workers: parallelWorkers }),
  }),
  startCleanup: (maxSeats = null) => request('POST', '/tasks/cleanup', { max_seats: maxSeats }),
  startCpaBatch: (joinMode = 'direct', target = null, batchSize = null, parallelWorkers = null) => request('POST', '/tasks/cpa-batch', {
    join_mode: joinMode,
    ...(target == null ? {} : { target }),
    ...(batchSize == null ? {} : { batch_size: batchSize }),
    ...(parallelWorkers == null ? {} : { parallel_workers: parallelWorkers }),
  }),
  getCpaBatchRuns: () => request('GET', '/cpa-batch/runs'),
  getCpaBatchRun: (runId) => request('GET', `/cpa-batch/runs/${encodeURIComponent(runId)}`),
  pauseCpaBatchRun: (runId) => request('POST', `/cpa-batch/runs/${encodeURIComponent(runId)}/pause`),
  resumeCpaBatchRun: (runId) => request('POST', `/cpa-batch/runs/${encodeURIComponent(runId)}/resume`),

  getTasks: () => request('GET', '/tasks'),
  getTask: (id) => request('GET', `/tasks/${id}`),
  stopAllTasks: () => request('POST', '/tasks/stop-all'),

  getAutoCheckConfig: () => request('GET', '/config/auto-check'),
  setAutoCheckConfig: (cfg) => request('PUT', '/config/auto-check', cfg),

  getTeamMembers: ({ refresh = false, allowBrowser = false } = {}) => request('GET', `/team/members?refresh=${refresh ? 'true' : 'false'}&allow_browser=${allowBrowser ? 'true' : 'false'}`),
  removeTeamMember: (payload) => request('POST', '/team/members/remove', payload),
  getLogs: (limit = 100, since = 0) => request('GET', `/logs?limit=${limit}&since=${since}`),
}
