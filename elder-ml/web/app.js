const $ = (s) => document.querySelector(s);
let lastState = null;
let selectedProfile = null;
let toastTimer = null;

const initials = (name) => name.split(' ').map((x) => x[0]).join('');
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtTime(value) { return new Date(value).toLocaleString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }); }
function fmtShort(value) { return new Date(value).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true }); }
function val(v, key) { return v?.[key] == null ? '—' : Math.round(v[key] * 10) / 10; }
function statusFor(c) { if (c.alerts.some((a) => a.display_tier === 'Red')) return ['RED ALERT', 'red']; if (c.alerts.length) return ['FOLLOW-UP', 'yellow']; return ['STABLE', 'stable']; }
function highlight(c, key) {
  for (const a of c.alerts) {
    const text = (a.summary + ' ' + a.reason_text).toLowerCase();
    if ((key === 'spo2' && /(oxygen|spo2|desaturat)/.test(text)) || (key === 'bp' && /(pressure|bp|hypertens)/.test(text)) || (key === 'hr' && /(heart|rate|af|fall)/.test(text))) return a.display_tier === 'Red' ? 'alert-red' : 'alert-yellow';
  }
  return '';
}
function vitalStrip(c) {
  const v = c.vitals;
  return `<div class="vital-strip"><div class="vital ${highlight(c, 'hr')}"><span>HEART RATE</span><b>${val(v, 'hr')} <small>bpm</small></b></div><div class="vital ${highlight(c, 'spo2')}"><span>OXYGEN</span><b>${val(v, 'spo2')}<small>%</small></b></div><div class="vital ${highlight(c, 'bp')}"><span>BLOOD PRESSURE</span><b>${val(v, 'sbp')}/${val(v, 'dbp')}</b></div><div class="vital"><span>TEMP</span><b>${val(v, 'temp')}<small>°C</small></b></div></div>`;
}
function clientCard(c) {
  const [status, cls] = statusFor(c);
  return `<article class="client-card directory-card" onclick="openProfile('${c.id}')"><div class="client-main"><div class="client-avatar">${initials(c.name)}</div><div class="client-identity"><b>${esc(c.name)}</b><small>${c.age} years · ${c.id}</small><div class="condition-tags">${c.conditions.map((x) => `<span class="condition-tag">${esc(x)}</span>`).join('')}</div></div>${vitalStrip(c)}<div class="client-status"><span class="status-pill ${cls}">${status}</span></div><span class="open-chevron">›</span></div></article>`;
}
function contactLine(contact) {
  return `<span class="contact-line"><b>${esc(contact.label)}</b><span>${esc(contact.name)}</span><code>${esc(contact.number)}</code></span>`;
}
function alertCard(a) {
  const client = lastState.clients.find((c) => c.id === a.person_id);
  const action = { New: 'Action initiated', 'Action initiated': 'Help reached', 'Help reached': 'Resolved' }[a.status];
  const progress = { New: 0, 'Action initiated': 1, 'Help reached': 2, Resolved: 3 }[a.status] || 0;
  const statusLabel = a.processing ? 'Voice note review in progress' : (a.status === 'New' ? 'Awaiting team action' : a.status);
  const workflowControls = a.processing
    ? '<span class="workflow-label">Preparing transcript and urgency summary…</span>'
    : `<button class="workflow-btn next" onclick="workflow('${esc(a.incident_id)}','${esc(action)}')">${action === 'Resolved' ? 'Mark resolved' : esc(action)} →</button>${client ? `<button class="workflow-btn" onclick="openProfile('${esc(a.person_id)}')">Open full profile</button>` : ''}`;
  const cases = a.similar_cases?.length ? a.similar_cases.map((item) => `<div class="case-row"><span class="case-date">${esc(fmtShort(item.date))}</span><span><b>${esc(item.summary)}</b><small>${esc(item.outcome)}</small></span><em class="case-tier ${item.tier === 'Red' ? 'case-red' : ''}">${esc(item.tier)}</em></div>`).join('') : '<div class="detail-line">No earlier matching case is listed.</div>';
  return `<article class="alert-item expanded-report ${a.display_tier === 'Red' ? 'flash' : ''}">
    <div class="alert-head"><div><span class="alert-person">${esc(a.client_name)} <small>${esc(a.source_label || a.person_id)}${client ? ` · ${client.age} years` : ''}</small></span><span class="report-badge">${esc(a.display_tier)} PRIORITY</span></div><span class="alert-time">Reported ${esc(fmtShort(a.start_ts))}</span></div>
    <p class="report-story">${esc(a.profile_story)}</p>
    <div class="report-vitals">${client ? vitalStrip(client) : ''}</div>
    <div class="report-section"><h3>Why this report appeared</h3><p>${esc(a.summary)}. ${esc(a.why_flagged)}</p></div>
    ${a.transcript ? `<div class="report-section"><h3>Voice note · ${esc(a.language || 'transcript')}</h3><p class="voice-transcript">${esc(a.transcript)}</p>${a.audio_url ? `<audio class="voice-audio" controls preload="none" src="${esc(a.audio_url)}">Audio playback is unavailable in this browser.</audio>` : ''}</div>` : ''}
    <div class="report-section"><h3>Possible context</h3><p>${esc(a.possible_context || lastState.clients.find((c) => c.id === a.person_id)?.possible_context || "A report highlights a pattern for staff review and cannot establish its cause.")}</p></div>
    <div class="report-section"><h3>Similar past cases <span>${a.similar_case_count || 0} on record</span></h3><div class="case-list">${cases}</div></div>
    <div class="report-bottom"><div class="report-section actions-section"><h3>Suggested team actions</h3><ul>${(a.actions || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
      <div class="report-section contacts-section"><h3>Contact directory</h3><p class="placeholder-note">${a.source_label === 'WhatsApp voice report' ? 'Sender number from the incoming message · confirm identity before calling' : 'Training-only contact placeholders · not for dialing'}</p>${(a.contacts || []).map(contactLine).join('')}</div></div>
    <div class="alert-workflow"><div class="workflow-label">${esc(statusLabel)}</div><div class="workflow-actions">${workflowControls}</div></div>
    <div class="progress-track"><div class="progress-fill" style="width:${Math.min(100, progress * 33.33)}%"></div></div>
  </article>`;
}
function switchView(view) {
  const isDashboard = view === 'dashboard';
  const isDirectory = view === 'directory';
  const isInbox = view === 'inbox';
  $('#dashboardView').classList.toggle('hidden', !isDashboard);
  $('#directoryView').classList.toggle('hidden', !isDirectory);
  $('#inboxView').classList.toggle('hidden', !isInbox);
  $('#dashboardNav').classList.toggle('active', isDashboard);
  $('#clientsNav').classList.toggle('active', isDirectory);
  $('#inboxNav').classList.toggle('active', isInbox);
  if (isDashboard) {
    $('#pageEyebrow').innerHTML = 'CARE NETWORK <span> / </span> ALERTS';
    $('#pageTitle').textContent = 'Good morning, team';
    $('#pageSubhead').textContent = 'A focused view of client wellbeing and active care alerts.';
  } else if (isDirectory) {
    $('#pageEyebrow').innerHTML = 'CARE NETWORK <span> / </span> CLIENT DIRECTORY';
    $('#pageTitle').textContent = 'Client directory';
    $('#pageSubhead').textContent = 'Select a client to review their profile, contacts, history and recent readings.';
  } else if (isInbox) {
    $('#pageEyebrow').innerHTML = 'CARE NETWORK <span> / </span> WHATSAPP INBOX';
    $('#pageTitle').textContent = 'WhatsApp inbox';
    $('#pageSubhead').textContent = 'Messages forwarded from the WhatsApp interface · text and voice notes from care clients.';
    renderInbox();
    // clear badge when viewing
    unreadInboxCount = 0;
    updateInboxBadge();
  }
}
function render(state) {
  lastState = state;
  $('#simTime').textContent = fmtTime(state.now);
  $('#speed').value = String(state.speed);
  $('#clientCount').textContent = String(state.clients.length).padStart(2, '0');
  $('#alertTotal').textContent = String(state.active_alerts.length).padStart(2, '0');
  $('#yellowTotal').textContent = String(state.yellow_count).padStart(2, '0');
  $('#redTotal').textContent = String(state.red_count).padStart(2, '0');
  $('#redBadge').textContent = state.red_count;
  $('#yellowBadge').textContent = state.yellow_count;
  const run = $('#runLabel');
  const pulse = $('.live-pulse');
  if (state.complete) { run.textContent = 'RECORD COMPLETE'; pulse.classList.remove('on'); }
  else if (state.paused && state.active_alerts.length) { run.textContent = 'PAUSED · TEAM ACTION'; pulse.classList.remove('on'); }
  else if (state.started && !state.paused) { run.textContent = 'UPDATING'; pulse.classList.add('on'); }
  else if (state.paused) { run.textContent = 'PAUSED'; pulse.classList.remove('on'); }
  else { run.textContent = 'READY'; pulse.classList.remove('on'); }
  $('#startBtn').disabled = state.started && !state.paused;
  $('#startBtn').innerHTML = state.started ? '▶&nbsp; Resume' : '▶&nbsp; Start';
  $('#pauseBtn').disabled = !state.started || state.paused;
  $('#clientList').innerHTML = state.clients.map(clientCard).join('');
  const red = state.active_alerts.filter((a) => a.display_tier === 'Red');
  const yellow = state.active_alerts.filter((a) => a.display_tier === 'Yellow');
  $('#redAlerts').innerHTML = red.length ? red.map(alertCard).join('') : '<div class="empty-state"><span>✓</span><b>No current red alerts</b><small>New reports will appear here</small></div>';
  $('#yellowAlerts').innerHTML = yellow.length ? yellow.map(alertCard).join('') : '<div class="empty-state"><span>✓</span><b>No current yellow alerts</b><small>New reports will appear here</small></div>';
  document.querySelectorAll('.pause-ribbon').forEach((x) => x.remove());
  if (state.paused && state.active_alerts.length) $('#redAlerts').insertAdjacentHTML('afterbegin', '<div class="pause-ribbon show">⏸ Timeline and incoming readings are held until the open reports are resolved.</div>');
  if (selectedProfile && $('#profileOverlay').classList.contains('open')) openProfile(selectedProfile, true);
}
async function refresh() { try { const response = await fetch('/api/state', { cache: 'no-store' }); if (response.status === 401) { showAccessGate(); return; } document.body.classList.remove('auth-check'); render(await response.json()); } catch { document.body.classList.remove('auth-check'); $('#runLabel').textContent = 'CONNECTION INTERRUPTED'; } }
async function post(path, body) { const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); if (response.status === 401) { showAccessGate(); throw new Error('Sign in required'); } const state = await response.json(); if (!response.ok) throw new Error(state.error || 'Request failed'); render(state); return state; }
window.workflow = async (id, action) => { await post('/api/workflow', { incident_id: id, action }); if (action === 'Resolved') showToast('Report closed · timeline resumed'); };
function showToast(message) { const toast = $('#toast'); toast.textContent = message; toast.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('show'), 2300); }

window.openProfile = async (id, silent = false) => {
  selectedProfile = id;
  try {
    const response = await fetch('/api/profile?id=' + encodeURIComponent(id));
    const p = await response.json();
    $('#drawerName').textContent = p.name;
    const latest = p.alerts.slice(-5).reverse();
    const examples = p.history_examples || [];
    const exampleHistory = examples.map((x) => `<div class="case-row"><span class="case-date">${esc(fmtShort(x.date))}</span><span><b>${esc(x.summary)}</b><small>${esc(x.outcome)}</small></span><em class="case-tier ${x.tier === 'Red' ? 'case-red' : ''}">${esc(x.tier)}</em></div>`).join('');
    const actions = latest[0]?.actions || ['Arrange a wellbeing call and ask about current symptoms.', 'Review the latest readings and follow the organisation’s escalation procedure if concerns continue.'];
    $('#drawerContent').innerHTML = `<div class="drawer-profile"><div class="drawer-avatar">${initials(p.name)}</div><div><b>${p.age} years · ${p.id}</b><div class="meta">Organisation client · training record</div></div></div>
      <div class="baseline-box"><b>Most recent readings</b> · ${fmtTime(p.now)}<br>${p.vitals.hr ?? '—'} bpm heart rate &nbsp;·&nbsp; ${p.vitals.spo2 ?? '—'}% oxygen<br>${p.vitals.sbp ?? '—'}/${p.vitals.dbp ?? '—'} mmHg blood pressure &nbsp;·&nbsp; ${p.vitals.temp ?? '—'}°C</div>
      <div class="drawer-section"><h3>Profile overview</h3><div class="detail-line">${esc(p.story)}</div></div>
      <div class="drawer-section"><h3>Profile watch context</h3><div class="focus-box">${esc(p.monitoring_focus)}</div></div><div class="drawer-section"><h3>Possible context for changes</h3><div class="detail-line">${esc(p.possible_context)}</div><div class="placeholder-note">Readings can prompt review but cannot determine a medical cause.</div></div>
      <div class="drawer-section"><h3>Conditions in record</h3>${p.conditions.map((x) => `<span class="detail-chip">${esc(x)}</span>`).join('')}</div>
      <div class="drawer-section"><h3>Medication list</h3><div class="detail-line">${p.medications.map(esc).join('<br>')}</div><div class="placeholder-note">Example entries for training. Verify medication records through approved systems.</div></div>
      <div class="drawer-section"><h3>Reported symptoms</h3><div class="detail-line">${p.symptoms.map(esc).join('<br>')}</div></div>
      <div class="drawer-section"><h3>Contact directory</h3><p class="placeholder-note">Training-only contact placeholders · not for dialing</p>${contactLine({ label: 'Client', name: p.name, number: p.client_phone })}${contactLine({ label: 'Family', name: p.family_name, number: p.family_phone })}${contactLine({ label: 'Hospital / care centre', name: p.care_site, number: p.care_phone })}</div>
      <div class="drawer-section"><h3>Suggested staff actions</h3><ul class="drawer-actions">${actions.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
      <div class="drawer-section"><h3>Past case history · training examples</h3><div class="case-list">${exampleHistory}</div></div>
      <div class="drawer-section"><h3>Recent vital trends · previous 3 hours</h3><div class="chart-legend"><span><i class="legend-dot" style="background:#d85b61"></i>Heart rate</span><span><i class="legend-dot" style="background:#408b7d"></i>Oxygen</span><span><i class="legend-dot" style="background:#dbac48"></i>Systolic pressure</span></div><div class="chart-wrap"><canvas id="trendChart"></canvas></div></div>
      <div class="drawer-section"><h3>Recent reports</h3>${latest.length ? latest.map((a) => `<div class="drawer-alert"><b>${esc(a.display_tier)} · ${esc(fmtShort(a.start_ts))}</b><br>${esc(a.summary)}</div>`).join('') : '<div class="detail-line">No reports reached in the current record.</div>'}</div>`;
    $('#profileOverlay').classList.add('open');
    $('#profileOverlay').setAttribute('aria-hidden', 'false');
    drawChart(p.history);
  } catch { if (!silent) showToast('Could not load this profile'); }
};
function drawChart(rows) {
  const canvas = $('#trendChart'); if (!canvas) return;
  const dpr = window.devicePixelRatio || 1; const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr; canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const w = rect.width; const h = rect.height; const pad = 22;
  ctx.strokeStyle = '#eef1f0'; ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) { const y = pad + i * (h - pad * 2) / 3; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  const series = [{ k: 'hr', c: '#d85b61', min: 45, max: 145 }, { k: 'spo2', c: '#408b7d', min: 80, max: 100 }, { k: 'sbp', c: '#dbac48', min: 90, max: 205 }];
  for (const item of series) {
    const stride = Math.max(1, Math.floor(rows.length / 60)); const data = rows.filter((_, i) => i % stride === 0).map((x) => x[item.k]);
    if (data.filter((x) => x != null).length < 2) continue;
    ctx.beginPath(); ctx.strokeStyle = item.c; ctx.lineWidth = 1.7; let begun = false;
    data.forEach((value, i) => { if (value == null) return; const x = pad + i * (w - pad * 2) / (data.length - 1); const y = h - pad - (value - item.min) / (item.max - item.min) * (h - pad * 2); if (!begun) { ctx.moveTo(x, y); begun = true; } else ctx.lineTo(x, y); }); ctx.stroke();
  }
}

$('#dashboardNav').addEventListener('click', () => switchView('dashboard'));
$('#clientsNav').addEventListener('click', () => switchView('directory'));
$('#inboxNav').addEventListener('click', () => switchView('inbox'));
$('#startBtn').addEventListener('click', () => post('/api/control', { action: lastState?.started ? 'resume' : 'start' }));
$('#pauseBtn').addEventListener('click', () => post('/api/control', { action: 'pause' }));
$('#resetBtn').addEventListener('click', async () => { if (confirm('Restart the training record from the beginning?')) { selectedProfile = null; $('#profileOverlay').classList.remove('open'); await post('/api/control', { action: 'reset' }); showToast('Record restarted'); } });
$('#speed').addEventListener('change', (event) => post('/api/speed', { speed: Number(event.target.value) }));

function showAccessGate() { document.body.classList.remove('auth-check'); $('#accessGate').classList.remove('hidden'); $('#accessGate').setAttribute('aria-hidden', 'false'); }
$('#accessForm').addEventListener('submit', async (event) => {
  event.preventDefault(); const error = $('#accessError'); error.textContent = 'Signing in…';
  try { await postLogin($('#accessPassword').value); $('#accessGate').classList.add('hidden'); $('#accessGate').setAttribute('aria-hidden', 'true'); $('#accessPassword').value = ''; error.textContent = ''; await refresh(); }
  catch (err) { error.textContent = err.message; }
});
async function postLogin(password) {
  const response = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Sign-in failed'); return result;
}
$('#closeDrawer').addEventListener('click', () => { $('#profileOverlay').classList.remove('open'); $('#profileOverlay').setAttribute('aria-hidden', 'true'); selectedProfile = null; });
$('#profileOverlay').addEventListener('click', (event) => { if (event.target.id === 'profileOverlay') $('#closeDrawer').click(); });
// ── WhatsApp inbox ────────────────────────────────────────────────────
let unreadInboxCount = 0;
let lastInboxLength = 0;
let waPopupTimer = null;

function getInboxMessages() {
  try { return JSON.parse(localStorage.getItem('elderml_wa_inbox') || '[]'); } catch { return []; }
}

function fmtInboxTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true }) +
      ' · ' + d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  } catch { return ''; }
}

function renderInbox() {
  const msgs = getInboxMessages();
  const list = $('#inboxList');
  if (!list) return;
  if (!msgs.length) {
    list.innerHTML = '<div class="empty-state"><span>💬</span><b>No messages received yet</b><small>Send a message from the WhatsApp interface — it will appear here.</small></div>';
    $('#inboxMeta').textContent = 'No messages yet';
    $('#inboxLive').style.display = 'none';
    return;
  }
  $('#inboxMeta').textContent = `${msgs.length} message${msgs.length !== 1 ? 's' : ''} received`;
  $('#inboxLive').style.display = 'inline-block';
  list.innerHTML = msgs.map((m) => {
    const isVoice = m.type === 'voice';
    const icon = isVoice ? '🎤' : '💬';
    const preview = isVoice
      ? `Voice note · ${fmtDurationInbox(m.duration || 0)}${m.transcript ? `<div class="inbox-transcript">${esc(m.transcript)}</div>` : ''}`
      : `<span class="inbox-text-preview">${esc(m.text || '')}</span>`;
    const audioBlock = isVoice && m.audioUrl
      ? `<audio class="inbox-audio" controls preload="none" src="${esc(m.audioUrl)}">Audio unavailable</audio>`
      : '';
    return `<article class="inbox-item">
      <div class="inbox-icon">${icon}</div>
      <div class="inbox-body">
        <div class="inbox-top">
          <span class="inbox-sender">${esc(m.contactName || m.contactId || 'Unknown')}</span>
          <span class="inbox-time">${fmtInboxTime(m.timestamp)}</span>
        </div>
        <div class="inbox-preview">${preview}</div>
        ${audioBlock}
      </div>
    </article>`;
  }).join('');
}

function fmtDurationInbox(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function showWaPopup(msg) {
  const popup = $('#waPopup');
  if (!popup) return;
  const isVoice = msg.type === 'voice';
  $('#waPopupName').textContent = msg.contactName || msg.contactId || 'WhatsApp';
  $('#waPopupPreview').textContent = isVoice
    ? `🎤 Voice note · ${fmtDurationInbox(msg.duration || 0)}`
    : `💬 ${(msg.text || '').substring(0, 60)}`;
  popup.classList.add('show');
  popup.setAttribute('aria-hidden', 'false');
  clearTimeout(waPopupTimer);
  waPopupTimer = setTimeout(dismissWaPopup, 7000);
}

function dismissWaPopup() {
  const popup = $('#waPopup');
  if (!popup) return;
  popup.classList.remove('show');
  popup.setAttribute('aria-hidden', 'true');
}

function checkInboxUpdates() {
  const msgs = getInboxMessages();
  if (msgs.length > lastInboxLength) {
    const newMsgs = msgs.slice(0, msgs.length - lastInboxLength);
    // show popup for the latest
    showWaPopup(newMsgs[0]);
    unreadInboxCount += newMsgs.length;
    updateInboxBadge();
    // if inbox view is open re-render it
    if (!$('#inboxView').classList.contains('hidden')) {
      renderInbox();
      unreadInboxCount = 0;
      updateInboxBadge();
    }
  }
  lastInboxLength = msgs.length;
}

function updateInboxBadge() {
  const badge = $('#inboxCount');
  if (!badge) return;
  if (unreadInboxCount > 0) {
    badge.textContent = unreadInboxCount;
    badge.style.display = 'inline-block';
  } else {
    badge.style.display = 'none';
  }
}

// Init inbox check
lastInboxLength = getInboxMessages().length;
setInterval(checkInboxUpdates, 800);

// Popup actions
if ($('#waPopupView')) {
  $('#waPopupView').addEventListener('click', () => {
    dismissWaPopup();
    switchView('inbox');
  });
}
if ($('#waPopupDismiss')) {
  $('#waPopupDismiss').addEventListener('click', dismissWaPopup);
}

// Open WhatsApp button
if ($('#openWhatsAppBtn')) {
  $('#openWhatsAppBtn').addEventListener('click', () => {
    window.open('/whatsapp.html', 'whatsapp-elder', 'width=1100,height=700,resizable=yes');
  });
}
if ($('#openWaFromInbox')) {
  $('#openWaFromInbox').addEventListener('click', () => {
    window.open('/whatsapp.html', 'whatsapp-elder', 'width=1100,height=700,resizable=yes');
  });
}

// Cross-window message listener
window.addEventListener('message', (event) => {
  if (event.data && event.data.source === 'whatsapp-elder') {
    checkInboxUpdates();
  }
});

refresh(); setInterval(refresh, 1500);
