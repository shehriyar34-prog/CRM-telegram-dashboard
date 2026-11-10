// CRM & Telegram Dashboard Client Application

let currentTab = 'overview';
let lastLogId = 0;
let allLogs = [];
let allMessages = [];
let statusPollInterval = null;
let logsPollInterval = null;

// ====================== Toast Notifications ======================
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ====================== Tab Navigation ======================
function initTabs() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  tabButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      switchTab(target);
    });
  });
}

function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabName}`);
  });

  if (tabName === 'settings') {
    loadSettings();
  } else if (tabName === 'logs') {
    renderTerminalLogs();
    scrollTerminalToBottom();
  } else if (tabName === 'messages') {
    renderMessagesTable();
  }
}

// ====================== Service Controls ======================
function initControls() {
  document.getElementById('btnStart').addEventListener('click', async () => {
    try {
      const res = await fetch('/api/service/start', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message, 'success');
        fetchStatus();
      } else {
        showToast(data.detail || 'Failed to start service', 'error');
      }
    } catch (e) {
      showToast('Network error starting service: ' + e.message, 'error');
    }
  });

  document.getElementById('btnStop').addEventListener('click', async () => {
    try {
      const res = await fetch('/api/service/stop', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message, 'warning');
        fetchStatus();
      } else {
        showToast(data.detail || 'Failed to stop service', 'error');
      }
    } catch (e) {
      showToast('Network error stopping service: ' + e.message, 'error');
    }
  });

  document.getElementById('btnRestart').addEventListener('click', async () => {
    try {
      showToast('Restarting background service...', 'info');
      const res = await fetch('/api/service/restart', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message, 'success');
        fetchStatus();
      } else {
        showToast(data.detail || 'Failed to restart service', 'error');
      }
    } catch (e) {
      showToast('Network error restarting service: ' + e.message, 'error');
    }
  });

  // Diagnostic Test Buttons
  document.getElementById('btnTestTelegram').addEventListener('click', async () => {
    const btn = document.getElementById('btnTestTelegram');
    btn.disabled = true;
    btn.innerHTML = 'Testing Telegram...';
    try {
      const res = await fetch('/api/test/telegram', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        showToast(`Telegram Connected! ${data.data.message}`, 'success');
      } else {
        showToast(`Telegram Error: ${data.data.message}`, 'error');
      }
      fetchStatus();
    } catch (e) {
      showToast('Error testing Telegram: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>
        <span>Test Telegram Connection</span>
      `;
    }
  });

  document.getElementById('btnTestCRM').addEventListener('click', async () => {
    const btn = document.getElementById('btnTestCRM');
    btn.disabled = true;
    btn.innerHTML = 'Testing CRM Panel...';
    try {
      const res = await fetch('/api/test/crm', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        showToast(`CRM Connected! Latency: ${data.data.latency_ms}ms`, 'success');
      } else {
        showToast(`CRM Error: ${data.data.message}`, 'error');
      }
      fetchStatus();
    } catch (e) {
      showToast('Error testing CRM: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11.08V8l-6-6H6a2 2 0 0 0-2 2v16c0 1.1.9 2 2 2h6"/><path d="M14 3v5h5M18 21l3-3m0 0l-3-3m3 3h-8"/></svg>
        <span>Test CRM Panel API</span>
      `;
    }
  });
}

// ====================== Status Polling ======================
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const json = await res.json();
    const s = json.data;
    updateStatusUI(s);
  } catch (e) {
    console.error('Status fetch error:', e);
  }
}

function updateStatusUI(s) {
  // Service Pill
  const pill = document.getElementById('serviceStatusPill');
  const label = pill.querySelector('.status-label');
  pill.className = 'service-pill ' + s.state.toLowerCase();
  label.textContent = s.state;

  // Header buttons state
  document.getElementById('btnStart').disabled = s.state === 'RUNNING' || s.state === 'STARTING';
  document.getElementById('btnStop').disabled = s.state === 'STOPPED';

  // Telegram Card
  const tgBadge = document.getElementById('tgStatusBadge');
  const tgStatus = s.telegram.status || 'UNKNOWN';
  tgBadge.textContent = tgStatus;
  tgBadge.className = 'status-tag ' + (tgStatus === 'CONNECTED' ? 'status-connected' : (tgStatus === 'ERROR' ? 'status-error' : 'status-unknown'));

  if (s.telegram.bot_username) {
    document.getElementById('tgBotUsername').textContent = '@' + s.telegram.bot_username;
  }
  if (s.last_sms_time) {
    document.getElementById('tgLastSms').textContent = s.last_sms_time;
  }

  // CRM Card
  const crmBadge = document.getElementById('crmStatusBadge');
  const crmStatus = s.crm.status || 'UNKNOWN';
  crmBadge.textContent = crmStatus;
  crmBadge.className = 'status-tag ' + (crmStatus === 'CONNECTED' ? 'status-connected' : (crmStatus === 'ERROR' ? 'status-error' : 'status-unknown'));

  document.getElementById('crmClientsCount').textContent = s.clients_loaded || '0';
  document.getElementById('crmNumbersCount').textContent = s.assigned_numbers_loaded || '0';

  // Metric Stats
  document.getElementById('statForwarded').textContent = s.total_sms_forwarded || '0';
  document.getElementById('statDetected').textContent = s.total_sms_detected || '0';
  document.getElementById('statSeen').textContent = s.seen_messages_count || '0';
  document.getElementById('statErrors').textContent = s.total_errors || '0';

  // Engine Uptime
  document.getElementById('statUptime').textContent = formatSeconds(s.uptime_seconds);
  if (s.start_time) {
    document.getElementById('statStartedAt').textContent = 'Started: ' + s.start_time;
  }
  if (s.last_poll_time) {
    document.getElementById('statLastPoll').textContent = s.last_poll_time;
  }
}

function formatSeconds(sec) {
  if (!sec || sec < 0) return '00:00:00';
  const h = Math.floor(sec / 3600).toString().padStart(2, '0');
  const m = Math.floor((sec % 3600) / 60).toString().padStart(2, '0');
  const s = Math.floor(sec % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

// ====================== Live Logs Management ======================
async function fetchLogs() {
  try {
    const url = lastLogId > 0 ? `/api/logs?min_id=${lastLogId}&limit=300` : '/api/logs?limit=300';
    const res = await fetch(url);
    if (!res.ok) return;
    const json = await res.json();
    const newLogs = json.data;

    if (newLogs.length > 0) {
      allLogs = allLogs.concat(newLogs);
      lastLogId = newLogs[newLogs.length - 1].id;

      // Keep up to 1000 in memory
      if (allLogs.length > 1000) {
        allLogs = allLogs.slice(allLogs.length - 1000);
      }

      document.getElementById('logsCountBadge').textContent = allLogs.length;
      renderMiniLogs();

      if (currentTab === 'logs') {
        renderTerminalLogs();
      }
    }
  } catch (e) {
    console.error('Logs fetch error:', e);
  }
}

function renderMiniLogs() {
  const container = document.getElementById('overviewMiniLogs');
  if (!container) return;

  const slice = allLogs.slice(-6);
  if (slice.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>No activity logs recorded yet.</p></div>';
    return;
  }

  container.innerHTML = slice.map(log => `
    <div class="log-line">
      <span class="log-time">${escapeHtml(log.timestamp.split(' ')[1] || log.timestamp)}</span>
      <span class="log-lvl log-lvl-${log.level}">${log.level}</span>
      <span class="log-src">[${log.source}]</span>
      <span class="log-msg">${escapeHtml(log.message)}</span>
    </div>
  `).join('');
}

function renderTerminalLogs() {
  const container = document.getElementById('fullTerminal');
  if (!container) return;

  const levelFilter = document.getElementById('logFilterLevel').value;
  const sourceFilter = document.getElementById('logFilterSource').value;
  const searchQuery = document.getElementById('logSearchInput').value.toLowerCase();

  const filtered = allLogs.filter(log => {
    if (levelFilter && log.level !== levelFilter) return false;
    if (sourceFilter && log.source !== sourceFilter) return false;
    if (searchQuery && !log.message.toLowerCase().includes(searchQuery)) return false;
    return true;
  });

  document.getElementById('logStatusText').textContent = `Showing ${filtered.length} of ${allLogs.length} entries`;

  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>No logs match the current filters.</p></div>';
    return;
  }

  container.innerHTML = filtered.map(log => `
    <div class="log-line">
      <span class="log-time">${escapeHtml(log.timestamp)}</span>
      <span class="log-lvl log-lvl-${log.level}">${log.level}</span>
      <span class="log-src">[${log.source}]</span>
      <span class="log-msg">${escapeHtml(log.message)}</span>
    </div>
  `).join('');

  if (document.getElementById('logAutoScroll').checked) {
    scrollTerminalToBottom();
  }
}

function scrollTerminalToBottom() {
  const container = document.getElementById('fullTerminal');
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

function initLogsToolbar() {
  document.getElementById('logFilterLevel').addEventListener('change', renderTerminalLogs);
  document.getElementById('logFilterSource').addEventListener('change', renderTerminalLogs);
  document.getElementById('logSearchInput').addEventListener('input', renderTerminalLogs);

  document.getElementById('btnClearLogs').addEventListener('click', async () => {
    if (!confirm('Clear all in-memory logs?')) return;
    try {
      await fetch('/api/logs/clear', { method: 'POST' });
      allLogs = [];
      lastLogId = 0;
      renderTerminalLogs();
      renderMiniLogs();
      showToast('Logs buffer cleared.', 'info');
    } catch (e) {
      showToast('Failed to clear logs: ' + e.message, 'error');
    }
  });

  document.getElementById('btnDownloadLogs').addEventListener('click', () => {
    const text = allLogs.map(l => `[${l.timestamp}] [${l.level}] [${l.source}] ${l.message}`).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `crm-bot-logs-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  });
}

// ====================== Forwarded SMS Feed ======================
async function fetchMessages() {
  try {
    const res = await fetch('/api/messages/recent');
    if (!res.ok) return;
    const json = await res.json();
    allMessages = json.data || [];

    renderOverviewSms();
    if (currentTab === 'messages') {
      renderMessagesTable();
    }
  } catch (e) {
    console.error('Messages fetch error:', e);
  }
}

function renderOverviewSms() {
  const container = document.getElementById('overviewSmsFeed');
  if (!container) return;

  const slice = allMessages.slice(0, 5);
  if (slice.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No SMS forwarded yet in this session.</p>
        <small>New incoming SMS from the CRM panel will appear here automatically.</small>
      </div>`;
    return;
  }

  container.innerHTML = slice.map(m => `
    <div class="sms-card-item">
      <div class="sms-header-row">
        <span class="sms-cli-tag">${escapeHtml(m.cli)}</span>
        <span class="sms-code-pill">CODE: ${escapeHtml(m.code)}</span>
      </div>
      <div class="sms-meta-row">
        <span>To: <strong>${escapeHtml(m.number)}</strong></span>
        <span>Client: <strong>${escapeHtml(m.client)}</strong></span>
        <span>Time: ${escapeHtml(m.time)}</span>
      </div>
      <div class="sms-content-box">${escapeHtml(m.content)}</div>
    </div>
  `).join('');
}

function renderMessagesTable() {
  const tbody = document.getElementById('fullSmsTableBody');
  if (!tbody) return;

  const search = (document.getElementById('smsSearchInput')?.value || '').toLowerCase();
  const filtered = allMessages.filter(m => {
    if (!search) return true;
    return m.number.toLowerCase().includes(search) ||
           m.cli.toLowerCase().includes(search) ||
           m.client.toLowerCase().includes(search) ||
           m.code.toLowerCase().includes(search) ||
           m.content.toLowerCase().includes(search);
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No messages found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(m => `
    <tr>
      <td>${escapeHtml(m.forwarded_at || m.time)}</td>
      <td><span class="sms-cli-tag">${escapeHtml(m.cli)}</span></td>
      <td><strong>${escapeHtml(m.client)}</strong></td>
      <td class="mono">${escapeHtml(m.number)}</td>
      <td><span class="sms-code-pill">${escapeHtml(m.code)}</span></td>
      <td>${escapeHtml(m.range)}</td>
      <td><span title="${escapeHtml(m.content)}">${escapeHtml(m.content.slice(0, 60))}${m.content.length > 60 ? '...' : ''}</span></td>
    </tr>
  `).join('');
}

// ====================== Health Report ======================
function initReportTab() {
  const dayPills = document.querySelectorAll('.day-pills .pill-btn');
  const customInput = document.getElementById('customDaysInput');

  dayPills.forEach(pill => {
    pill.addEventListener('click', () => {
      dayPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      customInput.value = pill.dataset.days;
    });
  });

  customInput.addEventListener('input', () => {
    const val = customInput.value;
    dayPills.forEach(p => {
      p.classList.toggle('active', p.dataset.days === val);
    });
  });

  document.getElementById('btnGenerateReport').addEventListener('click', async () => {
    const days = parseInt(customInput.value, 10) || 1;
    const sendTelegram = document.getElementById('sendReportToTelegram').checked;
    const btn = document.getElementById('btnGenerateReport');
    const preview = document.getElementById('reportPreviewArea');
    const actions = document.getElementById('reportActions');

    btn.disabled = true;
    btn.innerHTML = 'Generating Report...';
    preview.innerHTML = '<div class="empty-state"><p>⏳ Compiling number health statistics...</p></div>';

    try {
      const res = await fetch('/api/report/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days, send_telegram: sendTelegram })
      });
      const data = await res.json();
      if (res.ok) {
        preview.innerHTML = `
          <h4>Number Health Report (Last ${days} Day${days > 1 ? 's' : ''})</h4>
          <div class="report-rendered-box" id="rawReportText">${escapeHtml(data.report_html)}</div>
        `;
        actions.style.display = 'block';
        showToast(`Report for ${days} day(s) generated!`, 'success');
      } else {
        preview.innerHTML = `<div class="empty-state text-rose"><p>Error generating report: ${escapeHtml(data.detail)}</p></div>`;
      }
    } catch (e) {
      preview.innerHTML = `<div class="empty-state text-rose"><p>Network error: ${escapeHtml(e.message)}</p></div>`;
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        <span>Build Report</span>
      `;
    }
  });

  document.getElementById('btnCopyReport').addEventListener('click', () => {
    const box = document.getElementById('rawReportText');
    if (box) {
      navigator.clipboard.writeText(box.innerText).then(() => {
        showToast('Report copied to clipboard!', 'success');
      });
    }
  });
}

// ====================== Configuration Settings ======================
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const json = await res.json();
    const s = json.data;

    document.getElementById('cfgBotToken').value = s.bot_token || '';
    document.getElementById('cfgChatId').value = s.chat_id || '';
    document.getElementById('cfgPanelToken').value = s.panel_token || '';
    document.getElementById('cfgPanelBase').value = s.panel_base || 'https://imssms.org/api/v1';

    document.getElementById('cfgPollSeconds').value = s.poll_seconds || 5;
    document.getElementById('cfgClientRefresh').value = s.client_refresh_seconds || 300;
    document.getElementById('cfgMessagesPerPoll').value = s.messages_per_poll || 50;
    document.getElementById('cfgDailyHour').value = s.daily_report_hour_pkt !== null && s.daily_report_hour_pkt !== undefined ? s.daily_report_hour_pkt : '';

    document.getElementById('cfgReportDefaultDays').value = s.report_default_days || 1;
    document.getElementById('cfgReportMaxDays').value = s.report_max_days || 30;

    const mapping = json.client_by_number || {};
    document.getElementById('cfgClientByNumber').value = Object.keys(mapping).length > 0
      ? JSON.stringify(mapping, null, 2)
      : '';

    // Update target chat subtitle on card
    if (s.chat_id) {
      document.getElementById('tgTargetChat').textContent = `Chat: ${s.chat_id}`;
    }
    if (s.panel_base) {
      document.getElementById('crmBaseUrl').textContent = s.panel_base;
    }
    if (s.daily_report_hour_pkt !== null && s.daily_report_hour_pkt !== undefined) {
      document.getElementById('statDailyReport').textContent = `${s.daily_report_hour_pkt}:00 PKT`;
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

function toggleTokenMask(fieldId) {
  const f = document.getElementById(fieldId);
  if (f) {
    f.type = f.type === 'password' ? 'text' : 'password';
  }
}

function initSettings() {
  async function submitSettings(andRestart = false) {
    let clientMap = {};
    const rawMap = document.getElementById('cfgClientByNumber').value.trim();
    if (rawMap) {
      try {
        clientMap = JSON.parse(rawMap);
      } catch (err) {
        showToast('Invalid JSON in Manual Client Overrides: ' + err.message, 'error');
        return;
      }
    }

    const payload = {
      bot_token: document.getElementById('cfgBotToken').value.trim(),
      chat_id: document.getElementById('cfgChatId').value.trim(),
      panel_token: document.getElementById('cfgPanelToken').value.trim(),
      panel_base: document.getElementById('cfgPanelBase').value.trim(),
      poll_seconds: parseInt(document.getElementById('cfgPollSeconds').value, 10),
      client_refresh_seconds: parseInt(document.getElementById('cfgClientRefresh').value, 10),
      messages_per_poll: parseInt(document.getElementById('cfgMessagesPerPoll').value, 10),
      report_default_days: parseInt(document.getElementById('cfgReportDefaultDays').value, 10),
      report_max_days: parseInt(document.getElementById('cfgReportMaxDays').value, 10),
      daily_report_hour_pkt: document.getElementById('cfgDailyHour').value === '' ? null : parseInt(document.getElementById('cfgDailyHour').value, 10),
      client_by_number: clientMap,
    };

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        showToast('Settings saved successfully to .env!', 'success');
        if (andRestart) {
          showToast('Restarting service with updated configurations...', 'info');
          await fetch('/api/service/restart', { method: 'POST' });
          fetchStatus();
        }
      } else {
        showToast('Failed saving settings: ' + (data.detail || 'Unknown error'), 'error');
      }
    } catch (e) {
      showToast('Error saving settings: ' + e.message, 'error');
    }
  }

  document.getElementById('btnSaveSettings').addEventListener('click', () => submitSettings(false));
  document.getElementById('btnSaveAndRestart').addEventListener('click', () => submitSettings(true));
}

// ====================== Application Bootstrapping ======================
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initControls();
  initLogsToolbar();
  initReportTab();
  initSettings();

  // Initial loads
  fetchStatus();
  fetchLogs();
  fetchMessages();
  loadSettings();

  // Recurring live polling
  statusPollInterval = setInterval(fetchStatus, 2500);
  logsPollInterval = setInterval(fetchLogs, 2000);
  setInterval(fetchMessages, 4000);

  // SMS search input listener
  document.getElementById('smsSearchInput')?.addEventListener('input', renderMessagesTable);
});
