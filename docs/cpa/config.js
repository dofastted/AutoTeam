const fs = require('fs');
const path = require('path');

function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  const env = {};

  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf8');
    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#')) {
        continue;
      }

      const eqIndex = line.indexOf('=');
      if (eqIndex < 0) {
        continue;
      }

      const key = line.slice(0, eqIndex).trim();
      const value = line.slice(eqIndex + 1).trim();
      env[key] = value;
    }
  } else {
    console.warn('Warning: .env not found. Copy .env.example to .env and fill in the values.');
  }

  return {
    ...env,
    ...process.env,
  };
}

function parseBoolean(value, defaultValue = false) {
  const text = String(value ?? '').trim().toLowerCase();
  if (!text) {
    return defaultValue;
  }
  return ['1', 'true', 'yes', 'on'].includes(text);
}

function parseInteger(value, defaultValue = 0) {
  const parsed = Number.parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function parseOptionalInteger(value) {
  const text = String(value ?? '').trim();
  if (!text) {
    return null;
  }

  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function resolvePreferredPath(...candidates) {
  for (const candidate of candidates) {
    const value = String(candidate || '').trim();
    if (!value) {
      continue;
    }
    const resolved = path.resolve(__dirname, value);
    if (fs.existsSync(resolved)) {
      return resolved;
    }
  }

  const first = String(candidates.find((item) => String(item || '').trim()) || '').trim();
  return first ? path.resolve(__dirname, first) : '';
}

const env = loadEnv();

const defaultCfmailConfigPath = resolvePreferredPath(
  env.CFMAIL_CONFIG_PATH || 'cfmail_accounts.json',
  '..\\..\\chat_gpt_add_phone\\cfmail_accounts.json',
);

const defaultBrowserExecutablePath = resolvePreferredPath(
  env.BROWSER_EXECUTABLE_PATH || '',
  '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
  '/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
);

const config = {
  mailProvider: env.MAIL_PROVIDER || '2925',
  mail2925: {
    account: env.MAIL2925_ACCOUNT || '',
    password: env.MAIL2925_PASSWORD || '',
  },
  tempmail: {
    baseUrl: env.TEMPMAIL_BASE_URL || 'https://web2.temp-mail.org',
    proxy: env.TEMPMAIL_PROXY || '',
  },
  cfmail: {
    configPath: defaultCfmailConfigPath,
    profile: env.CFMAIL_PROFILE || 'auto',
    workerDomain: env.CFMAIL_WORKER_DOMAIN || '',
    emailDomain: env.CFMAIL_EMAIL_DOMAIN || '',
    adminPassword: env.CFMAIL_ADMIN_PASSWORD || '',
    mailSubdomains: env.CFMAIL_MAIL_SUBDOMAINS || '',
    failThreshold: parseInt(env.CFMAIL_FAIL_THRESHOLD || '3', 10),
    cooldownSeconds: parseInt(env.CFMAIL_COOLDOWN_SECONDS || '300', 10),
    proxy: env.CFMAIL_PROXY || env.PROXY || '',
  },
  outlookEmail: {
    baseUrl: env.OUTLOOK_EMAIL_BASE_URL || '',
    authMode: env.OUTLOOK_EMAIL_AUTH_MODE || 'auto',
    apiKey: env.OUTLOOK_EMAIL_API_KEY || '',
    loginPassword: env.OUTLOOK_EMAIL_LOGIN_PASSWORD || '',
    groupId: parseOptionalInteger(env.OUTLOOK_EMAIL_GROUP_ID),
    addressMode: env.OUTLOOK_EMAIL_ADDRESS_MODE || 'aliases-first',
    addressPool: env.OUTLOOK_EMAIL_ADDRESS_POOL || '',
    folder: env.OUTLOOK_EMAIL_FOLDER || 'all',
    fetchTop: parseInteger(env.OUTLOOK_EMAIL_FETCH_TOP, 10),
    disableUsedAccounts: parseBoolean(env.OUTLOOK_EMAIL_DISABLE_USED_ACCOUNTS, true),
    disableUsedStatus: env.OUTLOOK_EMAIL_DISABLE_USED_STATUS || 'inactive',
    usedAddressesPath: env.OUTLOOK_EMAIL_USED_ADDRESSES_PATH || path.join('output', 'outlook-email-used-addresses.json'),
  },
  browser: env.BROWSER || 'edge',
  seleniumUrl: env.SELENIUM_URL || 'http://127.0.0.1:4444',
  browserExecutablePath: defaultBrowserExecutablePath,
  browserCdpUrl: env.BROWSER_CDP_URL || '',
  roxyBrowserCdpUrl: env.ROXY_BROWSER_CDP_URL || '',
  roxyBrowserHttpUrl: env.ROXY_BROWSER_HTTP_URL || '',
  headless: parseBoolean(env.HEADLESS, false),
  backgroundWindow: parseBoolean(env.BACKGROUND_WINDOW, false),
  proxy: env.PROXY || '',
  proxyPoolFile: env.PROXY_POOL_FILE || '',
  proxyRotateOn429: parseBoolean(env.PROXY_ROTATE_ON_429, true),
  perAccountBrowser: parseBoolean(env.PER_ACCOUNT_BROWSER, true),
  interAccountDelayMs: parseInteger(env.INTER_ACCOUNT_DELAY_MS, 5000),
  rateLimitCooldownMs: parseInteger(env.RATE_LIMIT_COOLDOWN_MS, 180000),
  maxConsecutiveRateLimits: parseInteger(env.MAX_CONSECUTIVE_RATE_LIMITS, 2),
  otpWaitTimeout: parseInt(env.OTP_WAIT_TIMEOUT || '600', 10),
  otpResendWaitTimeout: parseInt(env.OTP_RESEND_WAIT_TIMEOUT || '300', 10),
  otpReceiveAttempts: parseInt(env.OTP_RECEIVE_ATTEMPTS || '5', 10),
  otpResendMaxAttempts: parseInt(env.OTP_RESEND_MAX_ATTEMPTS || '3', 10),
  otpPollIntervalSeconds: parseInt(env.OTP_POLL_INTERVAL_SECONDS || '5', 10),
  mail2925BaseUrl: 'https://mail.2925.com',
  mail2925AuthPath: path.resolve(__dirname, '../2925_mail_automation/.auth/storage-state.json'),
};

// Backward-compatible aliases used by existing local scripts.
config.mail2925Account = config.mail2925.account;
config.mail2925Password = config.mail2925.password;

module.exports = config;
