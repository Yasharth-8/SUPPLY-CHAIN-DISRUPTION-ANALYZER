/* ═══════════════════════════════════════════════════
   Supply Chain Disruption Analyser — app.js
   Light-theme dashboard with Evidence Library,
   Audit Log, Case History, and full trial transcript.
   Refactored for crystal clarity and simple language.
   ═══════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────
let currentCaseId = null;
let currentExposureCells = [];
let currentVerdictData = null;
let currentBriefingData = null;
let currentCaseFile = null;
let auditLog = [];
let pollInterval = null;
let caseSocket = null;
let caseHistory = [];

// ── Init ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadHistory();
  renderCaseHistory();
});

// ═══════════ HUMAN-FRIENDLY VOCABULARIES ═══════════

const COUNTRY_NAMES = {
  'GLOBAL': 'Global',
  'AE': 'United Arab Emirates',
  'SA': 'Saudi Arabia',
  'IQ': 'Iraq',
  'KW': 'Kuwait',
  'QA': 'Qatar',
  'OM': 'Oman',
  'IR': 'Iran',
  'EU': 'European Union',
  'IN': 'India',
  'CN': 'China',
  'JP': 'Japan',
  'KR': 'South Korea',
  'US': 'United States',
  'DE': 'Germany',
  'NL': 'Netherlands',
  'GB': 'United Kingdom',
  'RU': 'Russian Federation',
  'BR': 'Brazil',
  'SG': 'Singapore',
  'EG': 'Egypt',
  'TR': 'Turkey',
  'YE': 'Yemen',
  'UA': 'Ukraine',
  'KZ': 'Kazakhstan',
  'CH': 'Switzerland',
  'AT': 'Austria',
  'ZA': 'South Africa',
  'TW': 'Taiwan',
  'ID': 'Indonesia',
  'MY': 'Malaysia',
  'TH': 'Thailand',
  'PH': 'Philippines',
  'AU': 'Australia',
  'CA': 'Canada',
  'PL': 'Poland',
  'RO': 'Romania',
  'BG': 'Bulgaria',
  'NG': 'Nigeria',
  'AO': 'Angola',
  'MZ': 'Mozambique'
};

const COMMODITY_NAMES = {
  'urea': 'Fertilizer (Urea)',
  'crude_oil': 'Crude Oil',
  'refined_fuels': 'Refined Fuels (Gas & Diesel)',
  'natural_gas': 'Natural Gas (Pipeline)',
  'lng': 'Liquefied Natural Gas (LNG)',
  'electronic_components': 'Electronics & Auto Parts',
  'semiconductors': 'Semiconductors & Chips',
  'grain': 'Grain & Wheat',
  'rice': 'Rice & Agri-Exports',
  'wheat': 'Wheat & Cereals',
  'soybeans': 'Soybeans & Oilseeds',
  'dap': 'Phosphate Fertilizer (DAP)',
  'potash': 'Potash Fertilizer',
  'fertilizer': 'Fertilizer & Nutrients',
  'coal': 'Thermal & Coking Coal',
  'polymers': 'Polymers & Plastics',
  'sugar': 'Sugar & Agro Commodities',
  'iron_ore': 'Iron Ore & Steel Feedstock',
  'graphite': 'Graphite & Anode Materials',
  'general': 'Freight Cargo & Goods'
};

const COMMODITY_ICONS = {
  'crude_oil': '🛢️',
  'refined_fuels': '⛽',
  'natural_gas': '🔥',
  'lng': '🚢',
  'urea': '🌱',
  'dap': '🧪',
  'potash': '⛏️',
  'fertilizer': '🌾',
  'grain': '🌾',
  'rice': '🌾',
  'wheat': '🌾',
  'soybeans': '🌱',
  'sugar': '🍬',
  'iron_ore': '🏗️',
  'electronic_components': '🔌',
  'semiconductors': '💻',
  'coal': '⛏️',
  'graphite': '🔋',
  'polymers': '🧴',
  'general': '📦'
};

const METRIC_NAMES = {
  'delay_days': 'Delivery Delay',
  'volume_shortfall': 'Supply Shortfall',
  'production_at_risk': 'Factory Output at Risk',
  'import_volume_at_risk': 'Import Shipments at Risk',
  'price_increase': 'Price Surge',
  'permanent_capacity_loss': 'Permanent Capacity Loss'
};

const SECTOR_NAMES = {
  'energy': 'Energy',
  'energy.upstream': 'Oil & Gas Production',
  'energy.refining': 'Refining & Fuel Supply',
  'agriculture': 'Agriculture & Farming',
  'agriculture.farming': 'Crop Farming',
  'agriculture.processing': 'Food Processing',
  'chemicals': 'Chemical Industry',
  'chemicals.fertilizer': 'Fertilizer Manufacturing',
  'chemicals.petrochemicals': 'Petrochemicals',
  'manufacturing': 'Manufacturing & Industry',
  'automotive': 'Automotive Manufacturing',
  'electronics': 'Electronics & Tech',
  'logistics': 'Logistics & Transport',
  'logistics.shipping': 'Ocean Shipping Lines',
  'logistics.ports': 'Port Cargo Terminals',
  'mining': 'Mining & Extraction',
  'pharmaceuticals': 'Pharmaceuticals'
};

function formatCountry(code) {
  if (!code) return 'Global';
  const clean = cleanEnumStr(code).toUpperCase();
  return COUNTRY_NAMES[clean] || clean;
}

function formatCommodity(comm) {
  if (!comm) return 'General Goods';
  const clean = cleanEnumStr(comm).toLowerCase();
  return COMMODITY_NAMES[clean] || clean.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatMetric(m) {
  if (!m) return 'Disruption Impact';
  const clean = cleanEnumStr(m).toLowerCase();
  return METRIC_NAMES[clean] || clean.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatSector(s) {
  if (!s) return 'General';
  const clean = cleanEnumStr(s).toLowerCase();
  return SECTOR_NAMES[clean] || clean.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function cleanEnumStr(val) {
  if (!val) return '-';
  let s = String(val).trim();
  s = s.replace(/^(Country|Commodity|Sector|TimeHorizon|Metric)\./i, '');
  if (/^T_\d+_\d+[dD]$/i.test(s))
    s = s.replace(/^T_/i, '').replace(/_/g, '-').toLowerCase();
  else if (/^\d+_\d+[dD]$/i.test(s))
    s = s.replace(/_/g, '-').toLowerCase();
  return s;
}

function cleanThreadKey(key) {
  if (!key) return '';
  return String(key)
    .replace(/Country\./gi, '').replace(/Commodity\./gi, '')
    .replace(/Sector\./gi, '').replace(/TimeHorizon\./gi, '')
    .replace(/Metric\./gi, '')
    .replace(/T_(\d+)_(\d+)[dD]/gi, '$1-$2d');
}

function parseThreadKey(key) {
  if (!key) return null;
  const parts = String(key).split(':');
  if (parts.length < 5) return null;
  return {
    country: cleanEnumStr(parts[0]),
    sector: cleanEnumStr(parts[1]),
    commodity: cleanEnumStr(parts[2]),
    timeHorizon: cleanEnumStr(parts[3]),
    metric: cleanEnumStr(parts[4]),
    scenario: cleanEnumStr(parts[5] || 'base'),
  };
}

function horizonLabel(th) {
  const clean = cleanEnumStr(th || '').toLowerCase();
  if (clean === '0-7d' || clean === '0_7d') return 'Week 1 (Days 1–7)';
  if (clean === '8-21d' || clean === '8_21d') return 'Weeks 2–3 (Days 8–21)';
  if (clean === '22-60d' || clean === '22_60d') return 'Month 1–2 (Days 22–60)';
  if (clean === '61-90d' || clean === '61_90d') return 'Month 2–3 (Days 61–90)';
  if (clean === '90+d' || clean === '90_plus_d') return 'Ongoing (90+ Days)';
  return clean ? `Days ${clean}` : 'Immediate';
}

function formatFindingSummary(key, valStr, isMit) {
  const p = parseThreadKey(key);
  if (!p) return valStr;
  const comm = formatCommodity(p.commodity);
  const country = formatCountry(p.country);
  const rawMetric = p.metric.toLowerCase();
  const horiz = horizonLabel(p.timeHorizon);

  if (rawMetric === 'delay_days' || rawMetric.includes('delay')) {
    return `${valStr} delivery delay in ${comm} shipments arriving in ${country} (${horiz})`;
  } else if (rawMetric === 'volume_shortfall') {
    return isMit
      ? `${valStr} net ${comm} deficit after reserve buffers (${country} · ${horiz})`
      : `${valStr} direct ${comm} supply shortfall (${country} · ${horiz})`;
  } else if (rawMetric === 'import_volume_at_risk') {
    return `${valStr} inbound ${comm} imports at risk (${country} · ${horiz})`;
  } else if (rawMetric === 'production_at_risk') {
    return `${valStr} factory output cut in ${comm} manufacturing (${country} · ${horiz})`;
  } else if (rawMetric === 'price_increase') {
    return `${valStr} spot market price surge for ${comm} (${country} · ${horiz})`;
  } else {
    return `${valStr} in ${comm} for ${country} (${horiz})`;
  }
}

function formatNum(n) {
  if (n == null) return '-';
  const v = Number(n);
  if (isNaN(v)) return String(n);
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + ' M';
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + ' k';
  return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, '');
}

function formatUnit(unit) {
  if (!unit) return '';
  const u = String(unit).trim().toLowerCase();
  if (u.includes('barrel') && u.includes('usd') || u.includes('$/bbl') || u.includes('usd per barrel')) return '/ bbl';
  if (u === 'million bpd' || u === 'mbpd' || u.includes('million barrels per day')) return 'M bpd';
  if (u.includes('bpd') || u.includes('barrels per day')) return 'bpd';
  if (u.includes('percent') || u === '%') return '%';
  if (u.includes('million tonnes') || u.includes('million metric tonnes') || u.includes('mt')) return 'Mt';
  if (u.includes('metric tonnes') || u.includes('tonnes') || u.includes('tonne')) return 't';
  if (u.includes('day') || u === 'days') return 'days';
  return unit;
}

function formatValueRange(low, high, unit) {
  const fmtU = formatUnit(unit);
  const isPrice = String(unit).toLowerCase().includes('usd') || String(unit).toLowerCase().includes('barrel');
  const prefix = isPrice ? '$' : '';
  
  if (low == null && high == null) return '-';
  if (low != null && (high == null || low === high)) {
    return `${prefix}${formatNum(low)} ${fmtU}`.trim();
  }
  return `${prefix}${formatNum(low)} – ${prefix}${formatNum(high)} ${fmtU}`.trim();
}

function tierChipClass(tier) {
  if (tier <= 1) return 'chip-tier1';
  if (tier <= 2) return 'chip-tier2';
  if (tier <= 3) return 'chip-tier3';
  return 'chip-tier4';
}

function now() { return new Date().toLocaleTimeString('en-GB', { hour12: false }); }

// ═══════════ VIEW SWITCHING ═══════════

function switchView(view) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  document.getElementById('viewCases').classList.toggle('hidden', view !== 'cases');
  document.getElementById('viewEvidence').classList.toggle('hidden', view !== 'evidence');
  document.getElementById('viewAuditLog').classList.toggle('hidden', view !== 'audit');
  if (view === 'evidence') renderEvidenceLibrary();
  if (view === 'audit') renderAuditLog();
}

// ═══════════ PRESETS ═══════════

function setPreset(type) {
  const el = document.getElementById('questionInput');
  const presets = {
    hormuz: "If the Strait of Hormuz is partially blocked, what is Europe's and Asia's crude oil volume shortfall and refining exposure over the 0-7d and 8-21d windows, taking into account the Fujairah ADCOP bypass?",
    fertilizer: "China has tightened export quotas on urea fertilizer. How does this impact agricultural planting in Brazil and India over the next 60 days?",
    hypo: "What if a major dockworkers strike shuts down the Port of Rotterdam for 14 days? What is Germany's manufacturing and chemical import exposure?"
  };
  if (presets[type]) el.value = presets[type];
  el.focus();
}

// ═══════════ STATUS BADGE ═══════════

function updateStatusBadge(cls, text) {
  const b = document.getElementById('caseStatusBadge');
  b.className = `status-chip ${cls}`;
  b.textContent = text;
}

// ═══════════ CASE HISTORY ═══════════

function loadHistory() {
  try { caseHistory = JSON.parse(localStorage.getItem('scda_history') || '[]'); } catch { caseHistory = []; }
}
function saveHistory() {
  localStorage.setItem('scda_history', JSON.stringify(caseHistory.slice(0, 20)));
}
function renderCaseHistory() {
  const bar = document.getElementById('caseHistoryBar');
  const list = document.getElementById('caseHistoryList');
  if (!caseHistory.length) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  list.innerHTML = caseHistory.map((h, i) => `
    <button class="history-chip" onclick="loadHistoricCase(${i})" title="${escapeHtml(h.question)}">
      <span class="h-status ${escapeHtml(h.status || 'completed')}"></span>
      <span class="h-text">${escapeHtml(h.question.slice(0, 60))}${h.question.length > 60 ? '…' : ''}</span>
    </button>
  `).join('');
}

function loadHistoricCase(idx) {
  const h = caseHistory[idx];
  if (!h || !h.caseId) return;
  currentCaseId = h.caseId;
  document.getElementById('questionInput').value = h.question;
  showResults();
  updateStatusBadge('completed', h.statusText || 'Adjudicated');
  loadCaseData();
}

// ═══════════ NEW CASE ═══════════

function newCase() {
  if (currentCaseId) {
    const q = document.getElementById('questionInput').value.trim();
    if (q) {
      const existing = caseHistory.find(h => h.caseId === currentCaseId);
      if (!existing) {
        caseHistory.unshift({
          caseId: currentCaseId,
          question: q,
          status: document.getElementById('caseStatusBadge').classList.contains('dismissed') ? 'dismissed' : 'completed',
          statusText: document.getElementById('caseStatusBadge').textContent,
          time: new Date().toISOString()
        });
        saveHistory();
      }
    }
  }

  currentCaseId = null;
  currentExposureCells = [];
  currentVerdictData = null;
  currentBriefingData = null;
  currentCaseFile = null;
  auditLog = [];
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  if (caseSocket) { try { caseSocket.close(); } catch(e) {} caseSocket = null; }

  document.getElementById('questionInput').value = '';
  updateStatusBadge('idle', 'Ready');
  resetSubmitButton();
  document.getElementById('welcomeState').classList.remove('hidden');
  document.getElementById('processingState').classList.add('hidden');
  document.getElementById('dismissalState').classList.add('hidden');
  document.getElementById('resultsContainer').classList.add('hidden');
  switchView('cases');
  renderCaseHistory();
}

// ═══════════ SUBMIT CASE ═══════════

async function submitCase() {
  const question = document.getElementById('questionInput').value.trim();
  if (!question) { alert('Please enter a disruption scenario or question.'); return; }

  const btn = document.getElementById('btnSubmitCase');
  btn.disabled = true;
  btn.textContent = 'Analysing…';

  auditLog = [];
  addAuditEntry('case_submitted', 'Case submitted', question);

  document.getElementById('welcomeState').classList.add('hidden');
  document.getElementById('resultsContainer').classList.add('hidden');
  document.getElementById('dismissalState').classList.add('hidden');
  showProcessing();
  updateStatusBadge('active', 'Court in session');
  setPipelineStage('gatekeeper');

  try {
    const res = await fetch('/api/case/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });
    const data = await res.json();
    currentCaseId = data.case_id;
    addAuditEntry('case_accepted', 'Case ID assigned', `ID: ${data.case_id}`);

    initCaseWebSocket(currentCaseId);
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollCaseStatus, 3500);
  } catch (err) {
    alert(`Failed to submit case: ${err.message}`);
    addAuditEntry('error', 'Submission failed', err.message);
    resetSubmitButton();
    updateStatusBadge('dismissed', 'Error');
    document.getElementById('processingState').classList.add('hidden');
    document.getElementById('welcomeState').classList.remove('hidden');
  }
}

function resetSubmitButton() {
  const btn = document.getElementById('btnSubmitCase');
  btn.disabled = false;
  btn.textContent = 'Analyse';
}

// ═══════════ PIPELINE VISUALIZATION ═══════════

function showProcessing() {
  document.getElementById('processingState').classList.remove('hidden');
  document.querySelectorAll('.pipe-step').forEach(s => { s.classList.remove('active', 'done'); });
}

function setPipelineStage(stage) {
  const stages = ['gatekeeper', 'prosecutor', 'defence', 'rebuttals', 'judge'];
  const idx = stages.indexOf(stage);
  document.querySelectorAll('.pipe-step').forEach((s, i) => {
    s.classList.toggle('done', i < idx);
    s.classList.toggle('active', i === idx);
  });
  const labels = {
    gatekeeper: 'Step 1/5: Gatekeeper checking evidence pool and jurisdiction…',
    prosecutor: 'Step 2/5: Prosecutor calculating worst-case disruption impact…',
    defence: 'Step 3/5: Defence checking backup pipelines and emergency reserves…',
    rebuttals: 'Step 4/5: Both sides cross-examining numbers and evidence…',
    judge: 'Step 5/5: The Bench delivering verified findings…'
  };
  const el = document.getElementById('processingStage');
  if (labels[stage]) el.textContent = labels[stage];
}

function showResults() {
  document.getElementById('welcomeState').classList.add('hidden');
  document.getElementById('processingState').classList.add('hidden');
  document.getElementById('dismissalState').classList.add('hidden');
  document.getElementById('resultsContainer').classList.remove('hidden');
}

// ═══════════ POLLING ═══════════

async function pollCaseStatus() {
  if (!currentCaseId) return;
  try {
    const res = await fetch(`/api/case/${currentCaseId}/status`);
    const data = await res.json();

    if (data.current_stage) setPipelineStage(data.current_stage);

    if (data.status === 'completed') {
      clearInterval(pollInterval); pollInterval = null;
      const badge = data.is_degraded ? 'Adjudicated (fallback)'
        : data.is_partial_degraded ? 'Adjudicated (partial)'
        : 'Adjudicated';
      updateStatusBadge('completed', badge);
      addAuditEntry('completed', 'Case adjudicated', badge);
      resetSubmitButton();
      await loadCaseData();
    } else if (data.status === 'waiting_for_model') {
      updateStatusBadge('active', 'Waiting for model quota');
    } else if (data.status === 'dismissed') {
      clearInterval(pollInterval); pollInterval = null;
      updateStatusBadge('dismissed', 'Dismissed');
      addAuditEntry('dismissed', 'Case dismissed at intake', '');
      resetSubmitButton();
      await loadDismissalData();
    } else if (data.status === 'error') {
      clearInterval(pollInterval); pollInterval = null;
      updateStatusBadge('dismissed', 'Error');
      addAuditEntry('error', 'Execution error', data.error || '');
      resetSubmitButton();
      alert(`Case execution failed: ${data.error}`);
    }
  } catch (err) { console.error('Polling error:', err); }
}

// ═══════════ WEBSOCKET ═══════════

function initCaseWebSocket(caseId) {
  if (caseSocket) { try { caseSocket.close(); } catch(e) {} }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/api/ws/case/${caseId}`;
  try {
    caseSocket = new WebSocket(url);
    caseSocket.onmessage = async (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.stage) {
          setPipelineStage(msg.stage);
          addAuditEntry('stage', `Stage: ${msg.stage}`, msg.detail || '');
        }
        if (msg.event === 'trial_completed') {
          if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
          updateStatusBadge('completed', 'Adjudicated');
          addAuditEntry('completed', 'Trial completed via WebSocket', '');
          resetSubmitButton();
          await loadCaseData();
        } else if (msg.event === 'error') {
          if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
          updateStatusBadge('dismissed', 'Error');
          addAuditEntry('error', 'Error via WebSocket', msg.detail || '');
          resetSubmitButton();
        }
      } catch (e) { console.error('WS parse error:', e); }
    };
  } catch (err) {
    console.warn('WebSocket skipped, using polling fallback.');
  }
}

// ═══════════ LOAD CASE DATA ═══════════

async function loadCaseData() {
  showResults();

  try {
    const r = await fetch(`/api/case/${currentCaseId}/casefile`);
    currentCaseFile = await r.json();
    addAuditEntry('data', 'Case dossier loaded', `Pool: ${currentCaseFile.approved_pool?.length || 0} docs`);
  } catch (e) { console.error(e); }

  try {
    const r = await fetch(`/api/case/${currentCaseId}/verdict`);
    currentVerdictData = await r.json();
    addAuditEntry('data', 'Verdict loaded', `${currentVerdictData.threads?.length || 0} threads, ${currentVerdictData.rulings?.length || 0} rulings`);
  } catch (e) { console.error(e); }

  try {
    const r = await fetch(`/api/case/${currentCaseId}/exposure`);
    const d = await r.json();
    currentExposureCells = d.cells || [];
    addAuditEntry('data', 'Exposure matrix loaded', `${currentExposureCells.length} cells`);
  } catch (e) { console.error(e); }

  try {
    const r = await fetch(`/api/case/${currentCaseId}/briefing`);
    currentBriefingData = await r.json();
    addAuditEntry('data', 'Executive briefing loaded', '');
  } catch (e) { console.error(e); }

  renderCaseSummary();
  renderCourtLedger();
  renderImpactGrid();
  renderContestedFindings();
  renderEvidenceSummary();
  renderThreads();
  renderBriefing();
}

// ═══════════ DISMISSAL ═══════════

async function loadDismissalData() {
  try {
    const r = await fetch(`/api/case/${currentCaseId}/casefile`);
    const cf = await r.json();
    const d = cf.dismissal || cf;
    document.getElementById('processingState').classList.add('hidden');
    document.getElementById('welcomeState').classList.add('hidden');
    const el = document.getElementById('dismissalState');
    el.classList.remove('hidden');
    el.innerHTML = `
      <div class="card dismissal-card fade-in">
        <h3>❌ Case Dismissed at Intake</h3>
        <p>${escapeHtml(d.reasoning || 'Case not supported by evidence pool.')}</p>
        ${d.suggestion ? `<div class="suggestion">💡 ${escapeHtml(d.suggestion)}</div>` : ''}
      </div>`;
  } catch (e) { console.error(e); }
}

// ═══════════ RENDER: CASE SUMMARY ═══════════

function renderCaseSummary() {
  const cf = currentCaseFile;
  const b = currentBriefingData;
  if (!cf && !b) return;

  const chips = document.getElementById('caseChips');
  const eventStatus = cf?.event_status || b?.event_status || 'confirmed';
  const isHypo = eventStatus.toLowerCase() === 'hypothetical';
  chips.innerHTML = `
    <span class="chip mono" style="background:#F1F3F6;color:#334155">${escapeHtml(currentCaseId || 'CASE')}</span>
    <span class="chip ${isHypo ? 'chip-hypo' : 'chip-confirmed'}">${isHypo ? 'Hypothetical Scenario' : 'Verified Real Event'}</span>
    <span class="chip chip-date">As of ${escapeHtml(cf?.as_of_date || '-')}</span>
    <span class="chip chip-adjudicated">Adjudicated</span>
  `;

  const headlineEl = document.getElementById('caseHeadline');
  let headline = b?.headline;

  if (!headline) {
    const candidateCells = currentExposureCells.filter(c => (c.direct_exposure || c.mitigated_exposure));
    if (candidateCells.length > 0) {
      const top = candidateCells[0];
      const exp = top.mitigated_exposure || top.direct_exposure;
      const geo = formatCountry(top.country);
      const valStr = formatValueRange(exp.low, exp.high, exp.unit);
      const comm = formatCommodity(top.commodity);
      
      const mit = candidateCells.find(c => c.mitigated_exposure);
      if (mit) {
        const mExp = mit.mitigated_exposure;
        const mGeo = formatCountry(mit.country);
        const mVal = formatValueRange(mExp.low, mExp.high, mExp.unit);
        headline = `Disruption risks ${valStr} ${comm} shortage; emergency mitigation absorbs up to ${mVal} in ${mGeo}.`;
      } else {
        headline = `Disruption creates an accepted ${valStr} ${comm} exposure for ${geo}.`;
      }
    } else {
      headline = cf?.event_summary || b?.executive_summary || 'Adjudication completed.';
      headline = headline.replace(/^Adjudication completed for disruption:\s*/i, '');
    }
  }

  headlineEl.textContent = headline;

  const sub = document.getElementById('caseSubline');
  const rulings = currentVerdictData?.rulings || [];
  const threads = currentVerdictData?.threads || [];
  const rulingWord = rulings.length === 1 ? 'finding' : 'findings';
  const trackWord = threads.length === 1 ? 'debate track' : 'debate tracks';
  sub.textContent = `The Bench evaluated ${rulings.length} ${rulingWord} across ${threads.length} ${trackWord} under documentary burden-of-proof standards.`;

  renderKeyFindings();
}

function renderKeyFindings() {
  const container = document.getElementById('keyFindings');
  const cells = currentExposureCells.filter(c => c.direct_exposure || c.mitigated_exposure);
  if (!cells.length) { container.innerHTML = ''; return; }

  const top = cells.slice(0, 3);
  container.innerHTML = top.map(c => {
    const exp = c.mitigated_exposure || c.direct_exposure;
    const isMit = !!c.mitigated_exposure && !c.direct_exposure;
    const rawMetric = cleanEnumStr(c.metric || '');
    const rawComm = cleanEnumStr(c.commodity || 'general');
    const unitStr = String(exp?.unit || '').toLowerCase();
    
    let valStr = '';
    let metricTitle = formatMetric(rawMetric);
    if (rawMetric === 'delay_days' || unitStr.includes('day')) {
      valStr = exp.low === exp.high ? `+${formatNum(exp.low)} Days Late` : `+${formatNum(exp.low)}–${formatNum(exp.high)} Days Late`;
      metricTitle = 'Port & Cargo Delay';
    } else if (unitStr.includes('percent') || unitStr === '%' || unitStr.includes('shortfall') || unitStr.includes('risk')) {
      if (rawMetric === 'production_at_risk') {
        valStr = exp.low === exp.high ? `${formatNum(exp.low)}% Output Cut` : `${formatNum(exp.low)}–${formatNum(exp.high)}% Output Cut`;
        metricTitle = 'Factory Assembly at Risk';
      } else {
        valStr = exp.low === exp.high ? `${formatNum(exp.low)}% Deficit` : `${formatNum(exp.low)}–${formatNum(exp.high)}% Deficit`;
        metricTitle = 'Import Volume Shortfall';
      }
    } else if (rawMetric === 'price_increase' || unitStr.includes('usd') || unitStr.includes('barrel')) {
      valStr = exp.low === exp.high ? `+$${formatNum(exp.low)}/bbl Surge` : `+$${formatNum(exp.low)}–$${formatNum(exp.high)}/bbl Surge`;
      metricTitle = 'Spot Market Price Spike';
    } else {
      valStr = formatValueRange(exp?.low, exp?.high, exp?.unit);
    }

    const comm = formatCommodity(rawComm);
    const country = formatCountry(c.country);
    const icon = COMMODITY_ICONS[rawComm] || '📦';
    const type = isMit ? '🛡️ Buffered by strategic reserves' : '⚠️ Direct shortage (unmitigated)';
    const color = isMit ? 'cyan' : 'amber';
    const conf = (c.confidence || 'low').toLowerCase();
    const hLabel = horizonLabel(c.time_horizon);

    return `
      <div class="kf-card ${color} fade-in">
        <div class="kf-header">
          <span class="kf-icon">${icon}</span>
          <span class="kf-comm">${escapeHtml(comm)}</span>
        </div>
        <div class="kf-value">${valStr}</div>
        <div class="kf-label"><strong>${escapeHtml(comm)} · ${escapeHtml(metricTitle)}</strong></div>
        <div class="kf-sub-geo">📍 ${escapeHtml(country)} · ${escapeHtml(hLabel)}</div>
        <div style="font-size:11px;color:${isMit ? '#0E7490' : '#92400E'};font-weight:600;margin-top:4px">${type}</div>
        <div class="kf-conf"><span class="chip chip-date">Confidence: ${conf}</span></div>
      </div>`;
  }).join('');
}

// ═══════════ RENDER: COURT LEDGER ═══════════

function renderCourtLedger() {
  const b = currentBriefingData;
  const rulings = currentVerdictData?.rulings || [];
  const threads = currentVerdictData?.threads || [];

  // Mutually exclusive partitioning across all rulings
  let established = 0;
  let contested = 0;
  let uncontested = 0;
  let dismissed = 0;
  let conceded = 0;

  rulings.forEach(r => {
    const cls = (r.classification || '').toLowerCase();
    const rul = (r.ruling || '').toLowerCase();
    const hasPros = (r.prosecutor_claim_ids || []).length > 0;
    const hasDef = (r.defence_claim_ids || []).length > 0;
    const isUnopposed = (hasPros !== hasDef);

    if (rul === 'overruled' || rul.includes('insufficient') || cls.includes('insufficient')) {
      dismissed++;
    } else if (cls === 'conceded') {
      conceded++;
    } else if (rul === 'sustained' && cls === 'established' && !isUnopposed) {
      established++;
    } else if (isUnopposed) {
      uncontested++;
    } else {
      contested++;
    }
  });

  document.getElementById('ledgerBar').innerHTML = `
    ${established > 0 ? `<div style="flex:${established};background:#16A34A" title="Proven facts: ${established}"></div>` : ''}
    ${contested > 0 ? `<div style="flex:${contested};background:#F59E0B" title="Active disputes: ${contested}"></div>` : ''}
    ${uncontested > 0 ? `<div style="flex:${uncontested};background:#0284C7" title="Uncontested findings: ${uncontested}"></div>` : ''}
    ${conceded > 0 ? `<div style="flex:${conceded};background:#DC2626" title="Conceded points: ${conceded}"></div>` : ''}
    ${dismissed > 0 ? `<div style="flex:${dismissed};background:#94A3B8" title="Unproven / dismissed: ${dismissed}"></div>` : ''}
  `;

  document.getElementById('ledgerCounts').innerHTML = `
    <div class="ledger-row" title="Claims fully sustained with verified Tier 1-2 facts">
      <span><span class="chip chip-established">Proven Facts</span></span>
      <strong>${established}</strong>
    </div>
    <div class="ledger-row" title="Adjudicated disputes where Prosecutor and Defence debated opposing evidence">
      <span><span class="chip chip-contested">Active Disputes</span></span>
      <strong>${contested}</strong>
    </div>
    ${uncontested > 0 ? `
      <div class="ledger-row" title="Findings sustained from unopposed filings by one party">
        <span><span class="chip chip-unopposed">Uncontested Findings</span></span>
        <strong>${uncontested}</strong>
      </div>` : ''}
    ${conceded > 0 ? `
      <div class="ledger-row" title="Claims conceded by one side after seeing evidence">
        <span><span class="chip chip-conceded">Conceded</span></span>
        <strong>${conceded}</strong>
      </div>` : ''}
    ${dismissed > 0 ? `
      <div class="ledger-row" title="Claims dismissed or overruled due to insufficient evidence">
        <span><span class="chip chip-tier4">Unproven / Dismissed</span></span>
        <strong>${dismissed}</strong>
      </div>` : ''}
  `;

  document.getElementById('ledgerMeta').innerHTML = `
    <div class="meta-row"><span>Dispute tracks</span><strong class="meta-val">${threads.length}</strong></div>
    <div class="meta-row"><span>Total rulings</span><strong class="meta-val">${rulings.length}</strong></div>
    <div class="meta-row"><span>Evidence cards in pool</span><strong class="meta-val">${currentCaseFile?.approved_pool?.length || '-'}</strong></div>
  `;
}

// ═══════════ RENDER: TIME-TO-IMPACT GRID ═══════════

function formatCellImpact(rawMetric, exp, isMit, commodityDisplay, countryDisplay) {
  if (!exp) return '<span class="cell-none-text">— Not assessed —</span>';
  const unitStr = String(exp.unit || '').toLowerCase();
  const low = exp.low;
  const high = exp.high;
  const comm = commodityDisplay || 'Cargo';
  
  let valStr = '';
  let subStr = '';
  if (rawMetric === 'delay_days' || unitStr.includes('day')) {
    valStr = low === high ? `+${formatNum(low)} Days Late` : `+${formatNum(low)}–${formatNum(high)} Days Late`;
    subStr = `${comm} port delivery delay`;
  } else if (unitStr.includes('percent') || unitStr === '%' || unitStr.includes('shortfall') || unitStr.includes('risk')) {
    if (rawMetric === 'production_at_risk') {
      valStr = low === high ? `${formatNum(low)}% Output Cut` : `${formatNum(low)}–${formatNum(high)}% Output Cut`;
      subStr = `${comm} manufacturing line cut`;
    } else if (rawMetric === 'import_volume_at_risk') {
      valStr = low === high ? `${formatNum(low)}% Inbound Drop` : `${formatNum(low)}–${formatNum(high)}% Inbound Drop`;
      subStr = `Inbound ${comm} imports stalled`;
    } else {
      valStr = low === high ? `${formatNum(low)}% Deficit` : `${formatNum(low)}–${formatNum(high)}% Deficit`;
      subStr = `${comm} physical deficit`;
    }
  } else if (rawMetric === 'price_increase' || unitStr.includes('usd') || unitStr.includes('barrel')) {
    valStr = low === high ? `+$${formatNum(low)}/bbl` : `+$${formatNum(low)}–$${formatNum(high)}/bbl`;
    subStr = `${comm} spot price surge`;
  } else {
    valStr = formatValueRange(low, high, exp.unit);
    subStr = `${comm} volume gap`;
  }

  const tag = isMit ? '🛡️ Buffered by reserves' : '⚠️ Direct shortfall';
  return `<strong>${valStr}</strong><div class="cell-sub">${escapeHtml(subStr)}</div><span class="cell-tag ${isMit ? 'mit' : 'fill'}">${tag}</span>`;
}

function renderImpactGrid() {
  const grid = document.getElementById('impactGrid');
  const cells = currentExposureCells;
  if (!cells.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#94A3B8;padding:24px">No exposure data available.</div>';
    return;
  }

  const horizons = ['0-7d', '8-21d', '22-60d', '61-90d', '90+d'];
  const horizonHeaders = [
    { title: 'Week 1', sub: 'Days 1–7 (Immediate)' },
    { title: 'Weeks 2 – 3', sub: 'Days 8–21 (Short-term)' },
    { title: 'Month 1 – 2', sub: 'Days 22–60 (Mid-term)' },
    { title: 'Month 2 – 3', sub: 'Days 61–90 (Extended)' },
    { title: 'Long-term', sub: '90+ Days (Ongoing)' }
  ];

  // Group by: Metric + Commodity + Country + Sector
  const rowMap = new Map();
  cells.forEach(c => {
    const hasData = !!(c.direct_exposure || c.mitigated_exposure);
    const rawMetric = cleanEnumStr(c.metric || 'unknown');
    const rawComm = cleanEnumStr(c.commodity || 'general');
    const rawCountry = cleanEnumStr(c.country || 'Global');
    const rawSector = cleanEnumStr(c.sector || 'general');

    const key = `${rawMetric}|${rawComm}|${rawCountry}|${rawSector}`;
    if (!rowMap.has(key)) {
      rowMap.set(key, {
        rawMetric,
        rawComm,
        rawCountry,
        rawSector,
        metricDisplay: formatMetric(rawMetric),
        commodityDisplay: formatCommodity(rawComm),
        countryDisplay: formatCountry(rawCountry),
        sectorDisplay: formatSector(rawSector),
        icon: COMMODITY_ICONS[rawComm] || '📦',
        hasAnyRuling: false,
        cells: {}
      });
    }
    const row = rowMap.get(key);
    const h = cleanEnumStr(c.time_horizon || '');
    row.cells[h] = c;
    if (hasData) row.hasAnyRuling = true;
  });

  // Strictly filter out rows that have NO rulings across all 5 horizons!
  const activeRows = Array.from(rowMap.values()).filter(r => r.hasAnyRuling);

  if (!activeRows.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;color:#94A3B8;padding:24px">No active disruption rulings for this scenario.</div>';
    return;
  }

  let html = '<div class="table-corner-title"><strong>Tracked Impact</strong><span class="hd-sub">Commodity · Location</span></div>';
  horizonHeaders.forEach(h => {
    html += `<div class="hd"><span>${h.title}</span><span class="hd-sub">${h.sub}</span></div>`;
  });

  activeRows.forEach(row => {
    html += `
      <div class="rowlbl">
        <div class="rl-head">
          <span class="rl-icon">${row.icon}</span>
          <span class="rl-commodity">${escapeHtml(row.commodityDisplay)}</span>
        </div>
        <div class="rl-metric">${escapeHtml(row.metricDisplay)}</div>
        <div class="rl-sub">📍 ${escapeHtml(row.countryDisplay)} · ${escapeHtml(row.sectorDisplay)}</div>
      </div>`;
    horizons.forEach(h => {
      const c = row.cells[h];
      if (!c || (!c.direct_exposure && !c.mitigated_exposure)) {
        html += '<div class="cell not-assessed"><span class="cell-none-text">— Not assessed —</span></div>';
      } else {
        const isMit = !!c.mitigated_exposure && !c.direct_exposure;
        const exp = c.direct_exposure || c.mitigated_exposure;
        const cls = isMit ? 'mit' : 'fill';
        html += `<div class="cell ${cls}">${formatCellImpact(row.rawMetric, exp, isMit, row.commodityDisplay, row.countryDisplay)}</div>`;
      }
    });
  });

  grid.innerHTML = html;
}

// ═══════════ RENDER: CONTESTED FINDINGS ═══════════

function renderContestedFindings() {
  const container = document.getElementById('contestedFindings');
  const threads = currentVerdictData?.threads || [];
  const rulings = currentVerdictData?.rulings || [];
  const rulingsMap = {};
  rulings.forEach(r => {
    const tid = r.dispute_thread_id || r.thread_id;
    if (tid) rulingsMap[tid] = r;
    if (r.ruling_id) rulingsMap[r.ruling_id] = r;
  });

  const displayable = threads.filter(t => {
    const r = rulingsMap[t.thread_id];
    return r && (r.ruling === 'sustained' || r.ruling === 'partially_sustained');
  });

  const dismissedThreads = threads.filter(t => {
    const r = rulingsMap[t.thread_id];
    return r && (r.ruling === 'insufficient_evidence' || r.ruling === 'overruled');
  });

  if (!displayable.length && !dismissedThreads.length) {
    container.innerHTML = `<div class="eyebrow">Findings</div><p class="text-muted" style="margin-top:8px">No findings recorded for this case.</p>`;
    return;
  }

  let html = '';
  if (!displayable.length && dismissedThreads.length > 0) {
    html += `<div class="eyebrow">Findings</div><p class="text-muted" style="margin-top:8px;margin-bottom:16px">All submitted claims were unproven or dismissed due to insufficient evidence. See details below.</p>`;
  }

  displayable.forEach((t, i) => {
    const r = rulingsMap[t.thread_id];
    const est = r.accepted_estimate;
    const pClaims = t.prosecutor_claims || [];
    const dClaims = t.defence_claims || [];
    const hasBothSides = pClaims.length > 0 && dClaims.length > 0;

    const unit = est?.unit || '';
    const isMit = (est?.estimate_type || '').includes('mitigated');
    const rulingText = (r.ruling || 'sustained').replace(/_/g, ' ').toUpperCase();
    const benchValStr = est ? formatValueRange(est.low, est.high, unit) : (r.reasoning ? (r.reasoning.length > 70 ? r.reasoning.slice(0, 70) + '…' : r.reasoning) : 'Sustained finding');
    const subject = pClaims[0]?.subject || dClaims[0]?.subject || cleanThreadKey(t.key);
    const basisText = est?.basis || r.reasoning || '';

    if (hasBothSides) {
      const prosVal = Math.max(...pClaims.map(c => Number(c.estimate?.value) || 0), est.high || 0);
      const defVal = Math.min(...dClaims.map(c => Number(c.estimate?.value) || Infinity), est.low || 0);
      const prosValStr = formatValueRange(prosVal, prosVal, pClaims[0]?.estimate?.unit || unit);
      const defValStr = formatValueRange(defVal, defVal, dClaims[0]?.estimate?.unit || unit);

      html += `
        <div class="finding-block fade-in">
          <div class="finding-header-row">
            <span class="eyebrow">ACTIVE DISPUTE · ${escapeHtml(t.thread_id)}</span>
            <span class="chip ${isMit ? 'chip-tier2' : 'chip-tier1'}">${isMit ? '🛡️ Mitigated by Reserves' : '⚠️ Direct Shortage'}</span>
          </div>
          <h3 class="finding-title">${escapeHtml(subject)}</h3>
          <p class="finding-desc">${escapeHtml(r.reasoning || '')}</p>

          <div class="comparison-visual">
            <div class="party-pills">
              <div class="party-pill def">
                <span class="party-icon">🛡️</span>
                <div>
                  <div style="font-size:11px;color:#0E7490;font-weight:700">DEFENCE (RESILIENCE & MITIGATION)</div>
                  <div class="party-val">${defValStr}</div>
                  <div style="font-size:11px;color:#475569;margin-top:2px">${escapeHtml(dClaims[0]?.subject || 'Reserves & bypass buffer')}</div>
                </div>
              </div>
              <div class="vs-badge">VS</div>
              <div class="party-pill pros">
                <div>
                  <div style="font-size:11px;color:#B42318;font-weight:700">PROSECUTOR (DISRUPTION RISK)</div>
                  <div class="party-val">${prosValStr}</div>
                  <div style="font-size:11px;color:#475569;margin-top:2px">${escapeHtml(pClaims[0]?.subject || 'Unmitigated cutoff')}</div>
                </div>
                <span class="party-icon">⚔️</span>
              </div>
            </div>

            <div class="bench-verdict-callout ${isMit ? 'cyan' : 'amber'}">
              <div class="bench-callout-top">
                <span class="bench-callout-title">⚖️ The Bench Ruling: ${escapeHtml(rulingText)}</span>
              </div>
              <div class="bench-callout-range" style="margin-top:6px;font-size:14px;line-height:1.4">
                Accepted Finding: <strong>${escapeHtml(formatFindingSummary(t.key, benchValStr, isMit))}</strong>
              </div>
              ${basisText ? `<div class="bench-callout-basis"><strong>Judicial Basis:</strong> ${escapeHtml(basisText)}</div>` : ''}
            </div>
          </div>
        </div>`;
    } else {
      const isProsOnly = pClaims.length > 0;
      const claim = isProsOnly ? pClaims[0] : dClaims[0];
      const claimedValStr = formatValueRange(claim?.estimate?.value, claim?.estimate?.value, claim?.estimate?.unit || unit);

      html += `
        <div class="finding-block fade-in">
          <div class="finding-header-row">
            <span class="eyebrow">UNCONTESTED FINDING · ${escapeHtml(t.thread_id)}</span>
            <span class="chip chip-unopposed">${isProsOnly ? '⚔️ Prosecutor Unopposed' : '🛡️ Defence Unopposed'}</span>
          </div>
          <h3 class="finding-title">${escapeHtml(subject)}</h3>
          <p class="finding-desc">${escapeHtml(r.reasoning || '')}</p>

          <div class="unopposed-visual">
            <div class="unopposed-claimed">
              <span class="party-icon">${isProsOnly ? '⚔️' : '🛡️'}</span>
              <div>
                <div class="eyebrow" style="color:#64748B">${isProsOnly ? 'Prosecutor Claim' : 'Defence Claim'} (${escapeHtml(claim?.claim_type || 'sourced_fact')})</div>
                <div class="claimed-val"><strong>${claimedValStr}</strong> — <em>${escapeHtml(claim?.estimate?.method || 'Baseline calculation')}</em></div>
              </div>
            </div>

            <div class="bench-verdict-callout amber">
              <div class="bench-callout-top">
                <span class="bench-callout-title">⚖️ The Bench Ruling: ${escapeHtml(rulingText)}</span>
              </div>
              <div class="bench-callout-range" style="margin-top:6px;font-size:14px;line-height:1.4">
                Accepted Finding: <strong>${escapeHtml(formatFindingSummary(t.key, benchValStr, false))}</strong>
              </div>
              ${basisText ? `<div class="bench-callout-basis"><strong>Judicial Basis:</strong> ${escapeHtml(basisText)}</div>` : ''}
            </div>
          </div>
        </div>`;
    }
  });

  if (dismissedThreads.length > 0) {
    html += `
      <details class="dismissed-findings-details" style="margin-top:20px;background:#F8F9FB;border:1px solid #E2E5EA;border-radius:12px;padding:14px 18px">
        <summary style="font-size:13px;font-weight:700;color:#475569;cursor:pointer;display:flex;align-items:center;justify-content:space-between">
          <span>⚖️ Dismissed & Insufficient Points (${dismissedThreads.length})</span>
          <span style="font-size:11px;color:#94A3B8;font-weight:400">Click to expand ruled-against claims</span>
        </summary>
        <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px">
          ${dismissedThreads.map(t => {
            const r = rulingsMap[t.thread_id];
            const pClaims = t.prosecutor_claims || [];
            const dClaims = t.defence_claims || [];
            const isDef = dClaims.length > 0 && pClaims.length === 0;
            const sideIcon = isDef ? '🛡️ Defence Claim' : (pClaims.length > 0 ? '⚔️ Prosecutor Claim' : 'Dispute Point');
            const claim = isDef ? dClaims[0] : (pClaims[0] || null);
            const verdictLabel = (r?.ruling || 'insufficient_evidence').replace(/_/g, ' ').toUpperCase();

            return `
              <div style="background:#fff;border:1px solid #E2E5EA;border-radius:8px;padding:12px;font-size:12px">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                  <span style="font-weight:700;color:${isDef ? '#0E7490' : '#B42318'}">${sideIcon} [${escapeHtml(claim?.claim_id || t.thread_id)}]</span>
                  <span class="chip chip-tier4" style="font-size:10px">${escapeHtml(verdictLabel)}</span>
                </div>
                <div style="font-weight:600;color:#1E293B;margin-bottom:4px">${escapeHtml(claim?.subject || cleanThreadKey(t.key))}</div>
                ${claim?.estimate ? `<div style="color:#64748B;margin-bottom:6px">Claimed: ${formatValueRange(claim.estimate.value, claim.estimate.value, claim.estimate.unit)} (${escapeHtml(claim.estimate.method || '')})</div>` : ''}
                <div style="background:#F1F5F9;border-left:3px solid #94A3B8;padding:8px 10px;border-radius:4px;color:#334155;line-height:1.4">
                  <strong>Judicial Finding:</strong> ${escapeHtml(r?.reasoning || 'Insufficient documentary evidence in admitted pool to sustain finding.')}
                </div>
              </div>`;
          }).join('')}
        </div>
      </details>`;
  }

  container.innerHTML = html;
}

// ═══════════ RENDER: EVIDENCE SUMMARY ═══════════

function renderEvidenceSummary() {
  const container = document.getElementById('evidenceSummaryList');
  const b = currentBriefingData;
  const sources = b?.source_list || [];

  if (!sources.length) {
    const pool = currentCaseFile?.approved_pool || [];
    if (!pool.length) {
      container.innerHTML = '<p class="text-muted" style="margin-top:12px">No evidence sources registered.</p>';
      return;
    }
    container.innerHTML = '<div style="display:flex;flex-direction:column;gap:0;margin-top:8px">' +
      pool.slice(0, 8).map(d => `
        <div class="ev-item" onclick="openDocDrawer('${escapeHtml(d.doc_id || d)}')">
          <span class="chip ${tierChipClass(d.tier || 1)}">Tier ${d.tier || 1}</span>
          <div>
            <div class="ev-id">${escapeHtml(d.doc_id || d)}</div>
            <div class="ev-title">${escapeHtml(d.title || d.doc_id || d)}</div>
            <div class="ev-meta">${escapeHtml(formatCountry(d.country))} · ${escapeHtml(formatSector(d.sector))}</div>
          </div>
        </div>`).join('') + '</div>';
    return;
  }

  container.innerHTML = '<div style="display:flex;flex-direction:column;gap:0;margin-top:8px">' +
    sources.map(s => `
      <div class="ev-item" onclick="openDocDrawer('${escapeHtml(s.doc_id)}')">
        <span class="chip ${tierChipClass(s.tier)}">Tier ${s.tier}</span>
        <div>
          <div class="ev-id">${escapeHtml(s.doc_id)}</div>
          <div class="ev-title">${escapeHtml(s.title || '')}</div>
          <div class="ev-meta">${escapeHtml(formatCountry(s.country))} · ${escapeHtml(formatSector(s.sector))}</div>
        </div>
      </div>`).join('') + '</div>';
}

// ═══════════ RENDER: FULL TRIAL TRANSCRIPT ═══════════

function renderThreads() {
  const container = document.getElementById('disputeThreadsContainer');
  const threads = currentVerdictData?.threads || [];
  const rulings = currentVerdictData?.rulings || [];
  const prosResponses = currentVerdictData?.prosecutor_responses || [];
  const defResponses = currentVerdictData?.defence_responses || [];

  const rulingsMap = {};
  rulings.forEach(r => {
    rulingsMap[r.dispute_thread_id] = r;
    if (r.ruling_id) rulingsMap[r.ruling_id] = r;
  });

  const responseMap = {};
  [...prosResponses, ...defResponses].forEach(resp => {
    if (resp?.targets) {
      if (!responseMap[resp.targets]) responseMap[resp.targets] = [];
      responseMap[resp.targets].push(resp);
    }
  });

  let threadList = [...threads];

  if (!threadList.length && rulings.length) {
    rulings.forEach((r, idx) => {
      threadList.push({
        thread_id: r.dispute_thread_id || `DT-R${idx + 1}`,
        key: `RULING-${r.ruling_id}`,
        prosecutor_claims: (r.prosecutor_claim_ids || []).map(id => ({
          claim_id: id, subject: 'Adjudicated prosecution claim',
          estimate: { value: r.accepted_estimate?.high || '-', unit: r.accepted_estimate?.unit || '' },
          claim_type: 'sourced_fact', evidence: []
        })),
        defence_claims: (r.defence_claim_ids || []).map(id => ({
          claim_id: id, subject: 'Adjudicated defence claim',
          estimate: { value: r.accepted_estimate?.low || '-', unit: r.accepted_estimate?.unit || '' },
          claim_type: 'sourced_fact', evidence: []
        }))
      });
    });
  }

  if (!threadList.length) {
    container.innerHTML = '<p class="text-muted" style="padding:12px 0">No dispute threads available.</p>';
    return;
  }

  container.innerHTML = threadList.map(t => {
    const r = rulingsMap[t.thread_id];

    const renderR2 = (claimId) => {
      const resps = responseMap[claimId] || [];
      return resps.map(resp => `
        <div class="r2-box ${resp.response_type === 'concede' ? 'concede' : ''}">
          <div class="r2-header">
            <span class="r2-side ${resp.side === 'defence' ? 'def' : 'pros'}">
              ${resp.side === 'defence' ? '🛡️ Defence Rebuttal' : '⚔️ Prosecutor Rebuttal'} [${escapeHtml(resp.response_id || 'R2')}]
            </span>
            <span class="chip chip-date" style="font-size:10px">${escapeHtml((resp.response_type || 'rebut').toUpperCase())}</span>
          </div>
          <div class="r2-text">${escapeHtml(resp.reasoning || '')}</div>
          ${resp.concession_action ? `<div style="font-size:11px;color:#16A34A;margin-top:3px"><em>Action: ${escapeHtml(resp.concession_action)}</em></div>` : ''}
        </div>`).join('');
    };

    const pHtml = (t.prosecutor_claims || []).map(c => `
      <div class="claim-box">
        <div class="claim-header">
          <span class="side-pros">⚔️ PROSECUTOR [${escapeHtml(c.claim_id)}]</span>
          <span class="claim-type">${escapeHtml(c.claim_type || 'sourced_fact')}</span>
        </div>
        <div class="claim-subject">${escapeHtml(c.subject)}</div>
        <div class="claim-estimate"><strong>High Estimate:</strong> ${formatValueRange(c.estimate?.value, c.estimate?.value, c.estimate?.unit)}</div>
        <div class="claim-method"><em>Method:</em> ${escapeHtml(c.estimate?.method || 'Direct trade model')}</div>
        <div class="claim-citations">
          ${(c.evidence || []).map(ev => `
            <span class="citation-pill" onclick="openDocDrawer('${escapeHtml(ev.doc_id)}')">
              📄 ${escapeHtml(ev.doc_id)} ${ev.paragraph ? `[P${ev.paragraph}]` : ''}
            </span>`).join('')}
        </div>
        ${renderR2(c.claim_id)}
      </div>`).join('') || '<p class="no-claims">No Prosecutor claims in this thread.</p>';

    const dHtml = (t.defence_claims || []).map(c => `
      <div class="claim-box">
        <div class="claim-header">
          <span class="side-def">🛡️ DEFENCE [${escapeHtml(c.claim_id)}]</span>
          <span class="claim-type">${escapeHtml(c.claim_type || 'sourced_fact')}</span>
        </div>
        <div class="claim-subject">${escapeHtml(c.subject)}</div>
        <div class="claim-estimate"><strong>Low Estimate:</strong> ${formatValueRange(c.estimate?.value, c.estimate?.value, c.estimate?.unit)}</div>
        <div class="claim-method"><em>Method:</em> ${escapeHtml(c.estimate?.method || 'Mitigation & inventory model')}</div>
        <div class="claim-citations">
          ${(c.evidence || []).map(ev => `
            <span class="citation-pill" onclick="openDocDrawer('${escapeHtml(ev.doc_id)}')">
              📄 ${escapeHtml(ev.doc_id)} ${ev.paragraph ? `[P${ev.paragraph}]` : ''}
            </span>`).join('')}
        </div>
        ${renderR2(c.claim_id)}
      </div>`).join('') || '<p class="no-claims">No Defence claims in this thread.</p>';

    const verdictClass = r ? (r.ruling || 'partially_sustained').toLowerCase() : '';
    const verdictText = r ? (r.ruling || 'PARTIALLY SUSTAINED').replace(/_/g, ' ').toUpperCase() : '';

    return `
      <div class="dt-card fade-in">
        <div class="dt-head">
          <span class="dt-key">THREAD: ${escapeHtml(cleanThreadKey(t.key))}</span>
          <span class="dt-id">${escapeHtml(t.thread_id)}</span>
        </div>
        <div class="claims-grid">
          <div>${pHtml}</div>
          <div>${dHtml}</div>
        </div>
        ${r ? `
          <div class="ruling-box">
            <div class="ruling-header">
              <span class="ruling-badge ${verdictClass}">⚖️ THE BENCH: ${escapeHtml(verdictText)}</span>
              <span class="ruling-class">${escapeHtml(r.classification || 'CONTESTED')}</span>
            </div>
            <div class="ruling-text">${escapeHtml(r.reasoning || '')}</div>
            ${r.accepted_estimate ? `
              <span class="ruling-range ${(r.accepted_estimate.estimate_type || '').includes('mitigated') ? 'mitigated' : 'direct'}">
                Accepted Judicial Range: [${formatValueRange(r.accepted_estimate.low, r.accepted_estimate.high, r.accepted_estimate.unit)}] (${escapeHtml(r.accepted_estimate.estimate_type)})
              </span>` : ''}
          </div>` : ''}
      </div>`;
  }).join('');
}

// ═══════════ RENDER: BRIEFING ═══════════

function cleanFindingText(f) {
  if (!f) return '';
  return String(f)
    .replace(/^Ruling\s*\[[^\]]+\]\s*on\s*[^:]+:\s*[A-Z_]+\s*-\s*/i, '')
    .replace(/^(PARTIALLY_SUSTAINED|SUSTAINED|OVERRULED|INSUFFICIENT_EVIDENCE)\s*-\s*/i, '')
    .trim();
}

function renderBriefing() {
  const container = document.getElementById('briefingContainer');
  const b = currentBriefingData;
  if (!b) return;

  container.innerHTML = `
    <div class="briefing-wrap fade-in">
      <div class="briefing-head">
        <h2>Executive Judicial Briefing</h2>
        <span class="chip ${b.event_status?.toLowerCase() === 'hypothetical' ? 'chip-hypo' : 'chip-confirmed'}">
          ${escapeHtml((b.event_status || 'confirmed').toUpperCase())}
        </span>
      </div>

      ${b.is_degraded ? `
        <div class="briefing-degraded">
          ⚠️ <strong>Degraded execution:</strong> ${escapeHtml(b.degraded_reason || 'Cloud LLM models were rate-limited; grounded documentary evidence fallback active.')}
        </div>` : ''}

      <div class="briefing-summary">${escapeHtml(b.executive_summary)}</div>

      <div class="briefing-section">
        <h3>Proven Facts (Established Evidence)</h3>
        <ul class="briefing-list">
          ${(b.established_findings || []).map(f => {
            const clean = cleanFindingText(f);
            return `<li><strong>🟢 Proven:</strong> ${escapeHtml(clean)}</li>`;
          }).join('') || '<li>None</li>'}
        </ul>
      </div>

      <div class="briefing-section">
        <h3>Debated & Reconciled Findings (Active Disputes)</h3>
        <ul class="briefing-list">
          ${(b.contested_findings || []).map(f => {
            const clean = cleanFindingText(f);
            return `<li><strong>⚖️ Adjudicated:</strong> ${escapeHtml(clean)}</li>`;
          }).join('') || '<li>None</li>'}
        </ul>
      </div>

      <div class="briefing-section">
        <h3>Conceded Points</h3>
        <ul class="briefing-list">
          ${(b.conceded_findings || []).map(f => {
            const clean = cleanFindingText(f);
            return `<li><strong>🤝 Conceded:</strong> ${escapeHtml(clean)}</li>`;
          }).join('') || '<li>None</li>'}
        </ul>
      </div>

      ${(b.withdrawn_claims?.length) ? `
        <div class="briefing-section">
          <h3>Withdrawn Claims</h3>
          <ul class="briefing-list">
            ${b.withdrawn_claims.map(w => `<li><strong>[${escapeHtml(w.claim_id)}] ${escapeHtml(w.side)}:</strong> ${escapeHtml(w.subject)} — <em>${escapeHtml(w.reason)}</em></li>`).join('')}
          </ul>
        </div>` : ''}

      <div class="briefing-section">
        <h3>Outlook & Key Assumptions</h3>
        <p style="font-size:13px;color:#475569;margin-bottom:8px">${escapeHtml(b.outlook || '')}</p>
        <ul class="briefing-list">
          ${(b.assumptions || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}
        </ul>
      </div>

      <div class="briefing-section">
        <h3>Primary Documentary Sources</h3>
        <div class="briefing-sources">
          ${(b.source_list || []).map(s => `
            <span class="citation-pill" onclick="openDocDrawer('${escapeHtml(s.doc_id)}')">
              📄 ${escapeHtml(s.doc_id)}: ${escapeHtml(s.title || '')} (Tier ${s.tier})
            </span>`).join('')}
        </div>
      </div>
    </div>`;
}

// ═══════════ EVIDENCE LIBRARY VIEW ═══════════

async function renderEvidenceLibrary() {
  const grid = document.getElementById('evidenceLibraryGrid');
  const subline = document.getElementById('evidenceViewSubline');

  if (!currentCaseId || !currentCaseFile) {
    grid.innerHTML = '<div class="empty-notice card"><p>Submit a case to see its evidence library.</p></div>';
    subline.textContent = 'Evidence cards involved in the current case';
    return;
  }

  let cards = [];
  try {
    const res = await fetch(`/api/case/${currentCaseId}/evidence`);
    if (res.ok) {
      const data = await res.json();
      cards = data.cards || [];
    }
  } catch (e) {
    console.error('Failed to fetch evidence cards:', e);
  }

  const pool = currentCaseFile.approved_pool || [];
  const excluded = currentCaseFile.excluded_documents || [];
  const totalCount = cards.length || pool.length;
  subline.textContent = `${totalCount} evidence cards in pool · ${excluded.length} documents excluded`;

  if (!cards.length && !pool.length) {
    grid.innerHTML = '<div class="empty-notice card"><p>No evidence cards in the pool for this case.</p></div>';
    return;
  }

  const listToRender = cards.length ? cards : pool.map(d => ({ doc_id: d.doc_id || d, title: d.title || d, tier: d.tier || 1, country: d.country, sector: d.sector }));

  grid.innerHTML = listToRender.map(d => {
    const docId = d.doc_id || d.evidence_id || 'DOC';
    const title = d.title || docId;
    const tier = d.source_tier || d.tier || 1;
    const country = formatCountry(d.country);
    const sector = formatSector(d.sector || 'General');
    const quote = d.quote ? `<div class="ev-card-quote" style="font-size:12px;color:#475569;margin-top:6px;line-height:1.3;font-style:italic">"${escapeHtml(d.quote.slice(0, 140))}..."</div>` : '';

    return `
      <div class="card ev-card fade-in" onclick="openDocDrawer('${escapeHtml(docId)}')">
        <div class="ev-card-head">
          <span class="ev-card-id">${escapeHtml(docId)}</span>
          <span class="chip ${tierChipClass(tier)}">Tier ${tier}</span>
        </div>
        <div class="ev-card-title">${escapeHtml(title)}</div>
        <div class="ev-card-meta">
          <span>📍 ${escapeHtml(country)}</span>
          <span>🏷️ ${escapeHtml(sector)}</span>
        </div>
        ${quote}
      </div>`;
  }).join('');
}

// ═══════════ AUDIT LOG ═══════════

function addAuditEntry(type, title, detail) {
  auditLog.push({
    time: now(),
    type,
    title,
    detail: detail || '',
    timestamp: Date.now()
  });
}

function renderAuditLog() {
  const container = document.getElementById('auditLogTimeline');

  if (!auditLog.length) {
    container.innerHTML = '<div class="empty-notice card"><p>Submit a case to see its audit log.</p></div>';
    return;
  }

  container.innerHTML = auditLog.map(e => {
    let dotClass = 'done';
    if (e.type === 'error') dotClass = 'error';
    else if (e.type === 'stage' || e.type === 'active') dotClass = 'active';

    return `
      <div class="audit-entry ${dotClass} fade-in">
        <div class="audit-dot-col"><div class="audit-dot"></div></div>
        <div class="audit-body">
          <div class="audit-time">${escapeHtml(e.time)}</div>
          <div class="audit-title">${escapeHtml(e.title)}</div>
          ${e.detail ? `<div class="audit-detail">${escapeHtml(e.detail)}</div>` : ''}
        </div>
      </div>`;
  }).join('');
}

// ═══════════ EVIDENCE DRAWER ═══════════

async function openDocDrawer(docId) {
  const drawer = document.getElementById('evidenceDrawer');
  const overlay = document.getElementById('drawerOverlay');
  const title = document.getElementById('drawerTitle');
  const body = document.getElementById('drawerBody');

  title.textContent = `Document: ${docId}`;
  body.innerHTML = '<p class="text-muted" style="padding:20px 0">Loading document…</p>';
  drawer.classList.remove('hidden');
  overlay.classList.remove('hidden');

  try {
    const res = await fetch(`/api/docs/${docId}`);
    if (!res.ok) throw new Error('Document not found');
    const d = await res.json();

    let paragraphsHtml = '';
    if (d.paragraphs) {
      paragraphsHtml = Object.entries(d.paragraphs).map(([num, text]) => `
        <div class="drawer-para">
          <strong>[P${num}]</strong> ${escapeHtml(text)}
        </div>`).join('');
    } else if (d.table_rows) {
      paragraphsHtml = `<pre style="font-family:'JetBrains Mono',monospace;font-size:11px;overflow-x:auto;background:#F8F9FB;padding:12px;border-radius:8px">${escapeHtml(JSON.stringify(d.table_rows.slice(0, 5), null, 2))}</pre>`;
    } else {
      paragraphsHtml = `<p style="line-height:1.7">${escapeHtml(d.raw_text || '')}</p>`;
    }

    body.innerHTML = `
      <div class="drawer-meta">
        <div><strong>Title:</strong> ${escapeHtml(d.title || docId)}</div>
        <div><strong>Source:</strong> ${escapeHtml(d.source_name || '')} (${escapeHtml(d.source_type || '')})</div>
        <div><strong>Reliability:</strong> <span class="chip ${tierChipClass(d.reliability_tier)}">Tier ${d.reliability_tier}</span></div>
        <div><strong>Date:</strong> ${escapeHtml(d.pub_date || '')} ${escapeHtml(d.pub_time || '')}</div>
        <div><strong>Country:</strong> ${escapeHtml(formatCountry(d.country))} · <strong>Sector:</strong> ${escapeHtml(formatSector(d.sector))}</div>
      </div>
      <hr style="border:none;border-top:1px solid #E2E5EA;margin-bottom:16px">
      ${paragraphsHtml}`;
  } catch (err) {
    body.innerHTML = `<p style="color:#DC2626;padding:20px 0">Failed to load document: ${escapeHtml(err.message)}</p>`;
  }
}

function closeDrawer() {
  document.getElementById('evidenceDrawer').classList.add('hidden');
  document.getElementById('drawerOverlay').classList.add('hidden');
}
