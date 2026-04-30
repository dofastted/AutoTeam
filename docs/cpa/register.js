#!/usr/bin/env node
/**
 * ChatGPT registration CLI entry point.
 * Restored minimal batch registration flow for Outlook-backed sources.
 */

const fs = require('fs');
const path = require('path');
const config = require('./config');
const { ChatGPTClient } = require('./lib/chatgpt-client');
const { MailTempMail } = require('./lib/mail-tempmail');
const { MailOutlookEmail } = require('./lib/mail-outlook-email');
const { generateRandomPassword } = require('./lib/utils');
const { generateRandomUserInfo } = require('./lib/constants');
const { loadValidatedOutlookAccounts, parseOutlookSourceFile } = require('./lib/outlook-account-source');
const { writePasswordCheckpoint, writeSuccessArtifacts } = require('./lib/account-artifacts');
const { fetchChatgptSession } = require('./lib/chatgpt-session');
const { launchBrowser, normalizeBrowser } = require('./lib/browser-launch');
const { ProxyPool } = require('./lib/proxy-pool');
const {
  DEFAULT_MAX_FAILURE_ATTEMPTS,
  ensureBatchOutputDir,
  ensureOutputDir,
  loadRetryLedger,
  markSuccessfulAttempt,
  persistRetryLedger,
  recordFailureAttempt,
  sanitizeBatchBaseName,
} = require('./lib/retry-ledger');

function normalizeMailProvider(value) {
  const provider = String(value || 'outlookapi').trim().toLowerCase();
  if (['outlookapi', 'tempmail'].includes(provider)) {
    return provider;
  }
  throw new Error(`Unsupported mail provider: ${value}`);
}

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    email: '',
    password: '',
    count: 1,
    browser: normalizeBrowser(config.browser || 'edge'),
    headless: config.headless,
    backgroundWindow: config.backgroundWindow,
    proxy: config.proxy || '',
    mailProvider: normalizeMailProvider(config.mailProvider || 'outlookapi'),
    accountsFile: '',
    roxyBrowserCdpUrl: config.roxyBrowserCdpUrl || '',
    roxyBrowserHttpUrl: config.roxyBrowserHttpUrl || '',
    perAccountBrowser: config.perAccountBrowser !== false,
    perAccountTimeoutMs: Math.max(60000, Number(process.env.PER_ACCOUNT_TIMEOUT_MS || 900000)),
    interAccountDelayMs: Math.max(0, Number(config.interAccountDelayMs || 5000)),
    rateLimitCooldownMs: Math.max(0, Number(config.rateLimitCooldownMs || 180000)),
    maxConsecutiveRateLimits: Math.max(0, Number(config.maxConsecutiveRateLimits || 2)),
    proxyPoolFile: config.proxyPoolFile || '',
    rotateProxyOn429: config.proxyRotateOn429 !== false,
    credentialOnly: false,
  };

  for (let index = 0; index < args.length; index += 1) {
    switch (args[index]) {
      case '--email':
        opts.email = args[++index];
        break;
      case '--password':
        opts.password = args[++index];
        break;
      case '--count':
        opts.count = Math.max(1, Number.parseInt(args[++index], 10) || 1);
        break;
      case '--browser':
        opts.browser = normalizeBrowser(args[++index]);
        break;
      case '--headless':
        opts.headless = true;
        break;
      case '--background-window':
        opts.backgroundWindow = true;
        opts.headless = false;
        break;
      case '--proxy':
        opts.proxy = args[++index];
        break;
      case '--proxy-pool-file':
        opts.proxyPoolFile = args[++index];
        break;
      case '--mail-provider':
        opts.mailProvider = normalizeMailProvider(args[++index]);
        break;
      case '--accounts-file':
        opts.accountsFile = args[++index];
        break;
      case '--roxy-browser-cdp-url':
        opts.roxyBrowserCdpUrl = args[++index];
        break;
      case '--roxy-browser-http-url':
        opts.roxyBrowserHttpUrl = args[++index];
        break;
      case '--shared-browser':
        opts.perAccountBrowser = false;
        break;
      case '--per-account-browser':
        opts.perAccountBrowser = true;
        break;
      case '--per-account-timeout-ms':
        opts.perAccountTimeoutMs = Math.max(60000, Number.parseInt(args[++index], 10) || 60000);
        break;
      case '--inter-account-delay-ms':
        opts.interAccountDelayMs = Math.max(0, Number.parseInt(args[++index], 10) || 0);
        break;
      case '--rate-limit-cooldown-ms':
        opts.rateLimitCooldownMs = Math.max(0, Number.parseInt(args[++index], 10) || 0);
        break;
      case '--max-consecutive-rate-limits':
        opts.maxConsecutiveRateLimits = Math.max(0, Number.parseInt(args[++index], 10) || 0);
        break;
      case '--proxy-rotate-on-429':
        opts.rotateProxyOn429 = true;
        break;
      case '--no-proxy-rotate-on-429':
        opts.rotateProxyOn429 = false;
        break;
      case '--credential-only':
        opts.credentialOnly = true;
        break;
      case '--help':
        console.log(`
ChatGPT registration tool

Usage:
  node register.js --accounts-file output/clean-outlook.txt --mail-provider outlookapi --count 5
  node register.js --email user@example.com --mail-provider outlookapi

Options:
  --accounts-file            Outlook source file in email----mail_password----client_id----refresh_token format
  --email                    Register one explicit email
  --password                 Fixed ChatGPT password for single-account mode
  --count                    Number of accounts to process from source (default 1)
  --browser                  edge | chrome | roxy | selenium-chrome-oai
  --headless                 Run in headless mode
  --background-window        Keep browser UI but start minimized/in background when possible
  --proxy                    Browser proxy
  --proxy-pool-file          Proxy pool file, one proxy per line; bare host:port defaults to http://
  --roxy-browser-cdp-url     Roxy browser CDP websocket for reusing an opened window
  --roxy-browser-http-url    Roxy browser DevTools HTTP endpoint (resolved via /json/version)
  --mail-provider            outlookapi | tempmail
  --per-account-browser      Launch a fresh browser process per account (default)
  --shared-browser           Reuse one browser process across the whole batch
  --per-account-timeout-ms   Hard timeout for one account attempt
  --inter-account-delay-ms   Base delay between accounts
  --rate-limit-cooldown-ms   Extra cooldown after HTTP 429 failures
  --max-consecutive-rate-limits  Stop batch after this many consecutive HTTP 429 failures
  --proxy-rotate-on-429      Retry the same account on the next proxy after HTTP 429
  --no-proxy-rotate-on-429   Disable proxy rotation and keep legacy 429 handling
  --credential-only          Treat completed signup as success without session/OAuth artifacts
`);
        process.exit(0);
        break;
      default:
        throw new Error(`Unknown argument: ${args[index]}`);
    }
  }

  return opts;
}

function sanitizeFileName(value) {
  return String(value || 'unknown')
    .trim()
    .replace(/[<>:"/\\|?*\s]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '') || 'unknown';
}

function buildPerAccountFileName(prefix, result) {
  const emailLabel = sanitizeFileName(result.email || 'pending_email');
  return `${prefix}-${Date.now()}-${emailLabel}.json`;
}

function persistSingleAccountResult(result, { baseDir = __dirname } = {}) {
  const savedAt = new Date().toISOString();

  if (result.success) {
    const paths = result.credentialOnly
      ? writePasswordCheckpoint(result, { baseDir })
      : writeSuccessArtifacts(result, { baseDir });
    console.log(`Saved successful account to: ${paths.accountDir}`);
    console.log(`  Text: ${paths.textPath}`);
    if (paths.jsonPath) {
      console.log(`  JSON: ${paths.jsonPath}`);
      return paths.jsonPath;
    }
    return paths.textPath;
  }

  if (result.skipped) {
    console.log(`Skipped account without generating artifacts: ${result.email || '(pending email)'}`);
    if (result.error) {
      console.log(`  Reason: ${result.error}`);
    }
    return '';
  }

  const outputDir = ensureOutputDir(baseDir);
  const filePath = path.join(outputDir, buildPerAccountFileName('register-failure', result));
  const payload = {
    email: result.email,
    password: result.password,
    first_name: result.firstName,
    last_name: result.lastName,
    age: result.age,
    birthdate: result.birthdate,
    success: false,
    error: result.error || 'unknown error',
    saved_at: savedAt,
  };
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
  console.log(`Saved failed account to: ${filePath}`);
  return filePath;
}

function buildSourceLineFromAccountRecord(record) {
  if (record?.sourceRaw) {
    return String(record.sourceRaw).trim();
  }

  const email = String(record?.email || '').trim();
  const mailboxPassword = String(record?.mailboxPassword || record?.mailPassword || '').trim();
  const clientId = String(record?.clientId || '').trim();
  const refreshToken = String(record?.refreshToken || '').trim();

  if (!email || !mailboxPassword || !clientId || !refreshToken) {
    return '';
  }

  return [email, mailboxPassword, clientId, refreshToken].join('----');
}

function writeAccountsFilePartitions(sourceBatch, results, { baseDir = __dirname } = {}) {
  if (!sourceBatch?.sourcePath) {
    return null;
  }

  const allRecords = Array.isArray(sourceBatch.allRecords) ? sourceBatch.allRecords : [];
  const selectedRecords = Array.isArray(sourceBatch.selectedRecords) ? sourceBatch.selectedRecords : [];
  const validationSkippedRecords = Array.isArray(sourceBatch.validationSkippedRecords)
    ? sourceBatch.validationSkippedRecords
    : [];
  const allRecordsForPartition = allRecords.length > 0 ? allRecords : selectedRecords;
  const recordsByEmail = new Map(
    allRecordsForPartition.map((item) => [String(item.email || '').trim().toLowerCase(), item]),
  );
  const failedByEmail = new Map();
  const retryPendingEmails = new Set();
  const succeededEmails = new Set();
  const retryLedger = loadRetryLedger(baseDir, sourceBatch.sourcePath, {
    maxAttempts: DEFAULT_MAX_FAILURE_ATTEMPTS,
  });

  for (const result of results) {
    const emailKey = String(result?.email || '').trim().toLowerCase();
    if (!emailKey) {
      continue;
    }
    if (result.success) {
      markSuccessfulAttempt(retryLedger, { email: result.email });
      succeededEmails.add(emailKey);
      continue;
    }

    const sourceRecord = recordsByEmail.get(emailKey) || {};
    if (!result.skipped) {
      const retryEntry = recordFailureAttempt(retryLedger, {
        email: result.email,
        error: result.error || 'failed',
        failurePath: result.savedPath || '',
      });
      if (retryEntry && retryEntry.status !== 'failed') {
        retryPendingEmails.add(emailKey);
        continue;
      }
    }

    failedByEmail.set(emailKey, {
      email: result.email,
      sourceRaw: sourceRecord.sourceRaw || result.sourceRaw || '',
      mailboxPassword: sourceRecord.mailboxPassword || '',
      clientId: sourceRecord.clientId || '',
      refreshToken: sourceRecord.refreshToken || '',
      error: result.error || (result.skipped ? 'skipped' : 'failed'),
      status: result.skipped ? 'skipped' : 'failed',
      attemptCount: Number(retryLedger.entries[emailKey]?.attempt_count || 0),
      failureCategory: String(retryLedger.entries[emailKey]?.last_category || ''),
    });
  }

  for (const item of validationSkippedRecords) {
    const emailKey = String(item?.email || '').trim().toLowerCase();
    if (!emailKey || succeededEmails.has(emailKey) || failedByEmail.has(emailKey)) {
      continue;
    }
    const retryEntry = recordFailureAttempt(retryLedger, {
      email: item.email,
      error: item.skipReason || 'validation_skipped',
      failurePath: `validation-skip:${sourceBatch.attemptTag || Date.now()}:${emailKey}`,
    });
    if (retryEntry && retryEntry.status !== 'failed') {
      retryPendingEmails.add(emailKey);
      continue;
    }
    failedByEmail.set(emailKey, {
      email: item.email,
      sourceRaw: item.sourceRaw || '',
      mailboxPassword: item.mailPassword || '',
      clientId: item.clientId || '',
      refreshToken: item.refreshToken || '',
      error: item.skipReason || 'validation_skipped',
      status: 'validation_skipped',
      attemptCount: Number(retryLedger.entries[emailKey]?.attempt_count || 0),
      failureCategory: String(retryLedger.entries[emailKey]?.last_category || ''),
    });
  }

  const remainingRecords = [];
  const successRecords = [];
  const errorRecords = [];

  for (const item of allRecordsForPartition) {
    const emailKey = String(item?.email || '').trim().toLowerCase();
    if (!emailKey) {
      continue;
    }

    if (succeededEmails.has(emailKey)) {
      successRecords.push(item);
      continue;
    }

    if (failedByEmail.has(emailKey)) {
      errorRecords.push(failedByEmail.get(emailKey));
      continue;
    }

    if (retryPendingEmails.has(emailKey) || !succeededEmails.has(emailKey)) {
      remainingRecords.push(item);
    }
  }

  const batchesDir = ensureBatchOutputDir(baseDir);
  const timestamp = Date.now();
  const baseName = sanitizeBatchBaseName(sourceBatch.sourcePath);
  const remainingPath = path.join(batchesDir, `${baseName}-remaining-${timestamp}.txt`);
  const successPath = path.join(batchesDir, `${baseName}-success-${timestamp}.txt`);
  const errorPath = path.join(batchesDir, `${baseName}-error-${timestamp}.txt`);
  const latestSuccessPath = path.join(batchesDir, `${baseName}-success-latest.txt`);
  const latestErrorPath = path.join(batchesDir, `${baseName}-error-latest.txt`);
  const reportPath = path.join(batchesDir, `${baseName}-partition-${timestamp}.json`);
  const backupPath = path.join(batchesDir, `${baseName}-backup-${timestamp}.txt`);

  const remainingLines = remainingRecords.map(buildSourceLineFromAccountRecord).filter(Boolean);
  const successLines = successRecords.map(buildSourceLineFromAccountRecord).filter(Boolean);
  const errorLines = errorRecords.map(buildSourceLineFromAccountRecord).filter(Boolean);

  fs.copyFileSync(sourceBatch.sourcePath, backupPath);
  fs.writeFileSync(remainingPath, `${remainingLines.join('\n')}${remainingLines.length ? '\n' : ''}`);
  fs.writeFileSync(successPath, `${successLines.join('\n')}${successLines.length ? '\n' : ''}`);
  fs.writeFileSync(errorPath, `${errorLines.join('\n')}${errorLines.length ? '\n' : ''}`);
  fs.writeFileSync(latestSuccessPath, `${successLines.join('\n')}${successLines.length ? '\n' : ''}`);
  fs.writeFileSync(latestErrorPath, `${errorLines.join('\n')}${errorLines.length ? '\n' : ''}`);
  fs.writeFileSync(sourceBatch.sourcePath, `${remainingLines.join('\n')}${remainingLines.length ? '\n' : ''}`);
  const retryLedgerPaths = persistRetryLedger(baseDir, sourceBatch.sourcePath, retryLedger, { timestamp });

  const report = {
    source_path: sourceBatch.sourcePath,
    backup_path: backupPath,
    remaining_path: remainingPath,
    success_path: successPath,
    error_path: errorPath,
    latest_success_path: latestSuccessPath,
    latest_error_path: latestErrorPath,
    retry_ledger_path: retryLedgerPaths.stablePath,
    retry_ledger_snapshot_path: retryLedgerPaths.snapshotPath,
    remaining_count: remainingRecords.length,
    success_count: successRecords.length,
    error_count: errorRecords.length,
    validation_skipped_count: validationSkippedRecords.length,
    retry_pending_count: retryPendingEmails.size,
    deferred_count: 0,
    generated_at: new Date().toISOString(),
    error_items: errorRecords.map((item) => ({
      email: item.email,
      status: item.status,
      error: item.error,
      attempt_count: item.attemptCount || 0,
      failure_category: item.failureCategory || '',
    })),
    deferred_items: [],
  };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);

  console.log(`Updated source file after batch: ${sourceBatch.sourcePath}`);
  console.log(`  Remaining: ${remainingPath}`);
  console.log(`  Success: ${successPath}`);
  console.log(`  Error: ${errorPath}`);
  console.log(`  Latest Success: ${latestSuccessPath}`);
  console.log(`  Latest Error: ${latestErrorPath}`);
  console.log(`  Retry Ledger: ${retryLedgerPaths.stablePath}`);
  console.log(`  Backup: ${backupPath}`);
  console.log(`  Report: ${reportPath}`);

  return report;
}

function buildRuntimeConfig(opts) {
  return {
    ...config,
    baseDir: __dirname,
    proxy: opts.proxy || config.proxy || '',
    mailProvider: opts.mailProvider,
    headless: opts.headless,
    backgroundWindow: opts.backgroundWindow,
    browser: opts.browser,
    roxyBrowserCdpUrl: opts.roxyBrowserCdpUrl || config.roxyBrowserCdpUrl || '',
    roxyBrowserHttpUrl: opts.roxyBrowserHttpUrl || config.roxyBrowserHttpUrl || '',
    tempmail: {
      ...(config.tempmail || {}),
      proxy: opts.proxy || config.tempmail?.proxy || config.proxy || '',
    },
    outlookEmail: {
      ...(config.outlookEmail || {}),
    },
  };
}

function isRateLimitError(error) {
  return /HTTP 429/i.test(String(error || ''));
}

function resolveActiveProxy(opts) {
  if (opts.proxyPool instanceof ProxyPool && opts.proxyPool.hasCurrent()) {
    return opts.proxyPool.current();
  }
  return String(opts.proxy || '').trim();
}

async function closeBrowserInstance(browser) {
  if (browser) {
    await browser.close().catch(() => {});
  }
}

function splitUserInfo(userInfo) {
  const parts = String(userInfo?.name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return {
      firstName: parts[0],
      lastName: parts.slice(1).join(' '),
    };
  }
  return {
    firstName: parts[0] || 'Alex',
    lastName: 'Smith',
  };
}

async function wait(delayMs) {
  if (!delayMs || delayMs <= 0) {
    return;
  }
  await new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function createMailbox(opts) {
  const runtimeConfig = buildRuntimeConfig(opts);
  if (opts.mailProvider === 'tempmail') {
    return {
      mailbox: new MailTempMail(runtimeConfig),
      mailContext: null,
    };
  }

  if (opts.mailProvider === 'outlookapi') {
    return {
      mailbox: new MailOutlookEmail(runtimeConfig),
      mailContext: null,
    };
  }

  throw new Error(`Unsupported mail provider for current register flow: ${opts.mailProvider}`);
}

function shouldAutoAllocateMailbox(provider, email = '') {
  if (provider === 'tempmail') {
    return true;
  }
  if (provider === 'outlookapi') {
    return !String(email || '').trim();
  }
  return false;
}

async function registerSingleAccount(account, browser, opts) {
  let email = account.email;
  const password = account.password;
  const runtimeConfig = buildRuntimeConfig(opts);
  const userInfo = generateRandomUserInfo();
  const { firstName, lastName } = splitUserInfo(userInfo);
  const birthdate = userInfo.birthdate;
  const age = userInfo.age;

  const result = {
    email,
    password,
    mailboxPassword: account.mailboxPassword || '',
    sourceClientId: account.clientId || '',
    sourceRefreshToken: account.refreshToken || '',
    sourceRaw: account.sourceRaw || '',
    firstName,
    lastName,
    age,
    birthdate,
    success: false,
    tokens: null,
    error: '',
    passwordVerified: false,
    chatgptPassword: '',
  };

  const chatgptContext = await browser.newContext({
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
  });
  const { mailbox, mailContext } = await createMailbox(opts);
  const perAccountTimeoutMs = Math.max(60000, Number(opts.perAccountTimeoutMs || 900000));
  let timeoutHandle = null;
  const clearAttemptTimeout = () => {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
      timeoutHandle = null;
    }
  };

  try {
    const timeoutPromise = new Promise((resolve) => {
      timeoutHandle = setTimeout(() => {
        result.error = `Registration timed out after ${perAccountTimeoutMs}ms`;
        console.log(result.error);
        resolve(result);
      }, perAccountTimeoutMs);
    });

    return await Promise.race([
      (async () => {
        await mailbox.init();
        if (shouldAutoAllocateMailbox(opts.mailProvider, email)) {
          const created = await mailbox.createAddress();
          email = created.address;
          result.email = email;
          console.log(`Allocated mailbox: ${email}`);
        }

        console.log(`\n${'='.repeat(60)}`);
        console.log(`Registering account: ${email}`);
        console.log(`Password: ${password}`);
        console.log(`Name: ${firstName} ${lastName}`);
        console.log(`Age: ${age}`);
        console.log(`Birthdate: ${birthdate}`);
        console.log(`${'='.repeat(60)}`);

        const chatgptPage = await chatgptContext.newPage();
        const chatgptClient = new ChatGPTClient(chatgptPage, {
          ...runtimeConfig,
          browserMode: opts.headless ? 'headless' : 'headed',
        });

        const applySessionInfoToResult = (sessionInfo) => {
          result.success = true;
          result.chatgptSession = sessionInfo.sessionData || null;
          result.tokens = {
            accessToken: sessionInfo.accessToken || '',
            refreshToken: result.tokens?.refreshToken || '',
            idToken: sessionInfo.idToken || '',
            accountId: sessionInfo.accountId || '',
            expiresIn: sessionInfo.expiresIn || 3600,
          };
          result.sessionToken = sessionInfo.sessionToken || sessionInfo.sessionData?.sessionToken || '';
        };

        const tryChatgptSessionReuse = async (label) => {
          try {
            console.log(`${label}: navigating to ChatGPT home before session capture...`);
            await chatgptPage.goto('https://chatgpt.com/', {
              waitUntil: 'domcontentloaded',
              timeout: 30000,
            }).catch(async () => {
              await chatgptPage.reload({
                waitUntil: 'domcontentloaded',
                timeout: 30000,
              }).catch(() => {});
            });
            await chatgptPage.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
            console.log(`${label}: checking ChatGPT web session...`);
            const sessionInfo = await fetchChatgptSession(chatgptPage);
            applySessionInfoToResult(sessionInfo);
            console.log(`${label}: ChatGPT session token extracted.`);
            console.log(`  Account ID: ${sessionInfo.accountId || ''}`);
            console.log(`  Access Token: ${(sessionInfo.accessToken || '').slice(0, 40)}...`);
            return true;
          } catch (error) {
            console.log(`${label}: ChatGPT session reuse unavailable: ${error.message}`);
            return false;
          }
        };

        console.log('\nStarting ChatGPT session-first flow...');
        const [regOk, regMsg] = await chatgptClient.registerCompleteFlow(
          email,
          password,
          firstName,
          lastName,
          birthdate,
          mailbox,
          {
            stopBeforeAboutYouSubmission: false,
            otpWaitTimeout: config.otpWaitTimeout,
            otpResendWaitTimeout: config.otpResendWaitTimeout,
          },
        );

        if (!regOk) {
          if (
            /already[_ ]exists/i.test(regMsg)
            || /user_already_exists/i.test(regMsg)
            || /An account already exists for this email address/i.test(regMsg)
          ) {
            result.skipped = true;
            result.error = `Skipped existing account: ${regMsg}`;
            console.log(result.error);
            return result;
          }

          result.error = `Registration failed: ${regMsg}`;
          console.log(result.error);
          return result;
        }

        console.log(`Registration result: ${regMsg}`);
        if (chatgptClient.lastFlowKind !== 'new_registration') {
          result.skipped = true;
          result.error = `Skipped non-password registration flow: ${chatgptClient.lastFlowKind || 'unknown'}`;
          console.log(result.error);
          return result;
        }

        result.success = true;
        result.passwordVerified = true;
        result.chatgptPassword = password;
        result.credentialOnly = Boolean(opts.credentialOnly);
        clearAttemptTimeout();

        if (opts.credentialOnly) {
          console.log('Credential-only mode: signup completed, skipping session/OAuth capture.');
          return result;
        }

        if (await tryChatgptSessionReuse('Post-register/login session reuse')) {
          return result;
        }

        result.success = false;
        result.passwordVerified = false;
        result.chatgptPassword = '';
        result.error = 'ChatGPT session reuse unavailable after login/registration';
        console.log(result.error);
        return result;
      })(),
      timeoutPromise,
    ]);
  } catch (error) {
    result.error = `Exception: ${error.message}`;
    console.log(`Registration exception: ${error.message}`);
    return result;
  } finally {
    clearAttemptTimeout();
    await mailbox.close().catch(() => {});
    if (mailContext) {
      await mailContext.close().catch(() => {});
    }
    await chatgptContext.close().catch(() => {});
  }
}

async function buildAccountsFromOptions(opts) {
  if (opts.accountsFile) {
    if (opts.mailProvider !== 'outlookapi') {
      throw new Error('--accounts-file currently requires --mail-provider outlookapi');
    }
    const parsedSource = parseOutlookSourceFile(opts.accountsFile);
    const validated = await loadValidatedOutlookAccounts({
      filePath: opts.accountsFile,
      baseUrl: config.outlookEmail?.baseUrl,
      apiKey: config.outlookEmail?.apiKey,
      folder: 'inbox',
      limit: Math.max(1, opts.count || 1),
      allowEmptyUsable: true,
      logger: console,
    });

    console.log(`Loaded ${validated.usableAccounts.length} usable Outlook accounts from ${validated.path}`);
    if (validated.skippedAccounts.length > 0) {
      const dirtyCount = validated.skippedAccounts.filter((item) => item.skipReason === 'chatgpt_history_detected').length;
      const unavailableCount = validated.skippedAccounts.filter((item) => item.skipReason === 'mailbox_unavailable').length;
      console.log(
        `Skipped ${validated.skippedAccounts.length} Outlook accounts during validation `
        + `(dirty=${dirtyCount}, unavailable=${unavailableCount}).`,
      );
    }

    return {
      accounts: validated.usableAccounts.map((item) => ({
        email: item.email,
        mailboxPassword: item.mailPassword,
        clientId: item.clientId,
        refreshToken: item.refreshToken,
        sourceRaw: item.raw,
        password: opts.password || generateRandomPassword(),
      })),
      sourceBatch: {
        sourcePath: validated.path,
        attemptTag: `${Date.now()}`,
        allRecords: parsedSource.accounts.map((item) => ({
          email: item.email,
          mailPassword: item.mailPassword,
          mailboxPassword: item.mailPassword,
          clientId: item.clientId,
          refreshToken: item.refreshToken,
          sourceRaw: item.raw,
        })),
        selectedRecords: validated.usableAccounts.map((item) => ({
          email: item.email,
          mailPassword: item.mailPassword,
          mailboxPassword: item.mailPassword,
          clientId: item.clientId,
          refreshToken: item.refreshToken,
          sourceRaw: item.raw,
        })),
        validationSkippedRecords: validated.skippedAccounts.map((item) => ({
          email: item.email,
          mailPassword: item.mailPassword,
          clientId: item.clientId,
          refreshToken: item.refreshToken,
          sourceRaw: item.raw,
          skipReason: item.skipReason || 'validation_skipped',
        })),
      },
    };
  }

  if (!opts.email) {
    throw new Error('Provide --accounts-file or --email');
  }

  return {
    accounts: [{
      email: opts.email,
      mailboxPassword: '',
      clientId: '',
      refreshToken: '',
      sourceRaw: '',
      password: opts.password || generateRandomPassword(),
    }],
    sourceBatch: null,
  };
}

function printSummary(results) {
  const successCount = results.filter((item) => item.success).length;
  const skippedCount = results.filter((item) => item.skipped).length;
  const failedCount = results.filter((item) => !item.success && !item.skipped).length;

  console.log(`\n\n${'='.repeat(60)}`);
  console.log('Registration summary');
  console.log('='.repeat(60));
  console.log(`  Total: ${results.length}`);
  console.log(`  Success: ${successCount}`);
  console.log(`  Skipped: ${skippedCount}`);
  console.log(`  Failed: ${failedCount}`);
}

async function runRegistrationBatch(accounts, opts, deps = {}) {
  const results = [];
  let sharedBrowser = null;
  let consecutiveRateLimits = 0;
  let proxyPoolExhausted = false;
  let batchHaltReason = '';
  const proxyRotationEnabled = opts.proxyPool instanceof ProxyPool && opts.rotateProxyOn429 !== false;
  const launchBrowserImpl = deps.launchBrowser || launchBrowser;
  const persistSingleAccountResultImpl = deps.persistSingleAccountResult || persistSingleAccountResult;
  const registerSingleAccountImpl = deps.registerSingleAccount || registerSingleAccount;
  const waitImpl = deps.wait || wait;

  try {
    for (let index = 0; index < accounts.length; index += 1) {
      const account = accounts[index];
      let result = null;

      while (true) {
        const attemptOpts = {
          ...opts,
          proxy: resolveActiveProxy(opts),
        };
        const proxyLabel = attemptOpts.proxy
          ? (opts.proxyPool instanceof ProxyPool && opts.proxyPool.hasCurrent()
            ? opts.proxyPool.describeCurrent()
            : attemptOpts.proxy)
          : '';

        if (proxyLabel) {
          console.log(`\nActive proxy: ${proxyLabel}`);
        }

        if (!opts.perAccountBrowser && !sharedBrowser) {
          sharedBrowser = await launchBrowserImpl(attemptOpts);
        }

        const browser = sharedBrowser || await launchBrowserImpl(attemptOpts);
        try {
          result = await registerSingleAccountImpl(account, browser, attemptOpts);
        } finally {
          if (!sharedBrowser) {
            await closeBrowserInstance(browser);
          }
        }

        if (!proxyRotationEnabled || !isRateLimitError(result?.error)) {
          break;
        }

        const exhaustedProxy = opts.proxyPool.current();
        const nextProxyEntry = opts.proxyPool.advance();
        if (!nextProxyEntry) {
          proxyPoolExhausted = true;
          opts.proxy = '';
          console.log(`\nHTTP 429 detected on proxy ${exhaustedProxy}; proxy pool exhausted.`);
          break;
        }

        opts.proxy = nextProxyEntry.normalized;
        console.log(
          `\nHTTP 429 detected on proxy ${exhaustedProxy}; `
          + `switching to ${opts.proxyPool.describeCurrent()} and retrying the same account.`,
        );

        if (sharedBrowser) {
          await closeBrowserInstance(sharedBrowser);
          sharedBrowser = null;
        }
      }

      results.push(result);
      result.savedPath = persistSingleAccountResultImpl(result);

      if (isRateLimitError(result.error)) {
        consecutiveRateLimits += 1;
      } else {
        consecutiveRateLimits = 0;
      }

      if (proxyPoolExhausted) {
        break;
      }

      const hasMore = index < accounts.length - 1;
      if (
        result.error
        && isRateLimitError(result.error)
        && !proxyRotationEnabled
        && opts.rateLimitCooldownMs > 0
        && hasMore
      ) {
        console.log(`\nHTTP 429 detected, cooling down for ${opts.rateLimitCooldownMs}ms before next account...`);
        await waitImpl(opts.rateLimitCooldownMs);
      } else if (hasMore && opts.interAccountDelayMs > 0) {
        console.log(`\nWaiting ${opts.interAccountDelayMs}ms before continuing...`);
        await waitImpl(opts.interAccountDelayMs);
      }

      if (
        !proxyRotationEnabled
        && opts.maxConsecutiveRateLimits > 0
        && consecutiveRateLimits >= opts.maxConsecutiveRateLimits
      ) {
        console.log(
          `\nStopping batch after ${consecutiveRateLimits} consecutive HTTP 429 failures to avoid burning more accounts.`,
        );
        break;
      }
    }
  } finally {
    if (sharedBrowser) {
      await closeBrowserInstance(sharedBrowser);
    }
  }

  results.proxyPoolExhausted = proxyPoolExhausted;
  results.batchHaltReason = batchHaltReason;
  return results;
}

function countTrailingRateLimitFailures(results = []) {
  if (!Array.isArray(results) || results.length === 0) {
    return 0;
  }

  let count = 0;
  for (let index = results.length - 1; index >= 0; index -= 1) {
    if (isRateLimitError(results[index]?.error)) {
      count += 1;
      continue;
    }
    break;
  }
  return count;
}

function initializeProxyPool(opts) {
  const proxyPoolFile = String(opts.proxyPoolFile || '').trim();
  if (!proxyPoolFile) {
    return null;
  }

  const proxyPool = ProxyPool.fromFile(proxyPoolFile);
  if (proxyPool.size() === 0) {
    throw new Error(`Proxy pool file is empty: ${proxyPool.path}`);
  }

  opts.proxyPool = proxyPool;
  opts.proxy = proxyPool.current();
  return proxyPool;
}

async function main() {
  const opts = parseArgs();
  const proxyPool = initializeProxyPool(opts);

  console.log('ChatGPT registration');
  console.log(`Browser: ${opts.browser}`);
  console.log(`Mail provider: ${opts.mailProvider}`);
  console.log(`Browser mode: ${opts.perAccountBrowser ? 'per-account' : 'shared'}`);
  if (proxyPool) {
    console.log(`Proxy pool: ${proxyPool.path} (${proxyPool.size()} proxies, start ${proxyPool.describeCurrent()})`);
  } else if (opts.proxy) {
    console.log(`Proxy: ${opts.proxy}`);
  }

  if (!opts.accountsFile) {
    const { accounts } = await buildAccountsFromOptions(opts);
    console.log(`Account count: ${accounts.length}`);
    const results = await runRegistrationBatch(accounts, opts);
    printSummary(results);
    if (results.proxyPoolExhausted) {
      console.log('Stopped after exhausting the proxy pool on HTTP 429.');
    } else if (results.batchHaltReason) {
      console.log(`Stopped after environmental gate/error: ${results.batchHaltReason}`);
    }
    return;
  }

  let iteration = 1;
  while (true) {
    const { accounts, sourceBatch } = await buildAccountsFromOptions(opts);
    const unresolvedCount = Array.isArray(sourceBatch?.allRecords) ? sourceBatch.allRecords.length : 0;
    console.log(`\nBatch iteration: ${iteration}`);
    console.log(`  Unresolved source rows: ${unresolvedCount}`);
    console.log(`  Selected usable accounts: ${accounts.length}`);
    console.log(`  Count limit: ${Math.max(1, opts.count || 1)}`);

    if (!sourceBatch || unresolvedCount === 0) {
      console.log('No unresolved accounts remain in source.');
      break;
    }

    const results = await runRegistrationBatch(accounts, opts);
    printSummary(results);
    const report = writeAccountsFilePartitions(sourceBatch, results);

    if (results.proxyPoolExhausted) {
      console.log('Batch halted after the proxy pool was exhausted by HTTP 429 responses.');
      break;
    }

    if (results.batchHaltReason) {
      console.log(`Batch halted after environmental gate/error: ${results.batchHaltReason}`);
      break;
    }

    if (
      report?.remaining_count
      && opts.maxConsecutiveRateLimits > 0
      && !proxyPool
      && countTrailingRateLimitFailures(results) >= opts.maxConsecutiveRateLimits
    ) {
      console.log('Batch halted after reaching the HTTP 429 threshold; leave remaining accounts for a later retry window.');
      break;
    }

    if (!report?.remaining_count) {
      console.log('All accounts are resolved; source is now empty.');
      break;
    }

    iteration += 1;
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`Fatal error: ${error.message}`);
    process.exit(1);
  });
}

module.exports = {
  buildSourceLineFromAccountRecord,
  buildRuntimeConfig,
  countTrailingRateLimitFailures,
  parseArgs,
  persistSingleAccountResult,
  runRegistrationBatch,
  writeAccountsFilePartitions,
};
