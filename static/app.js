/* Hermes Email Assistant — dashboard logic (vanilla JS, no framework).
 * All email / model text is inserted with textContent via h(), never innerHTML.
 *
 * Flow:  "Send email" popup -> Analyse -> live workflow INSIDE the popup (POST /api/analyze/stream)
 *        -> "Go to dashboard" -> latest emails / category pages -> click a row -> drawer -> Approve / Reject.
 */
(() => {
  'use strict';

  const DASH = 'dashboard';
  const CATS = [
    { id: 'Freight Quotation Enquiry', short: 'Freight', file: 'freight_quotation.md' },
    { id: 'Shipment Status', short: 'Shipment status', file: 'shipment_status.md' },
    { id: 'Documentation', short: 'Documentation', file: 'documentation.md' },
    { id: 'Payment', short: 'Payment', file: 'payment.md' },
    { id: 'General Business Email', short: 'General', file: 'general_business_email.md' },
    { id: 'Other', short: 'Other', file: 'other.md' },
  ];
  const KEY_V2 = 'hermes.dashboard.v2';
  const KEY_V1 = 'hermes.dashboard.v1';
  const THEME_KEY = 'hermes.theme';
  const VIEW_KEY = 'hermes.view';
  const MAX_ITEMS = 200;
  const DAY_MS = 24 * 60 * 60 * 1000;
  const HISTORY_SIZE = 5;
  const LATEST_SIZE = 10;

  // What a person should do next, in plain words.
  function nextStep(r) {
    switch (r.recommended_action) {
      case 'DRAFT_ACKNOWLEDGEMENT': return r.category === 'Freight Quotation Enquiry' ? 'Ready for quotation' : 'Acknowledge the sender';
      case 'ASK_FOR_INFORMATION': return 'Ask the customer for details';
      case 'VERIFY_INTERNALLY': return 'Check internally first';
      case 'FLAG_FOR_REVIEW': return 'Needs human review';
      case 'NO_REPLY_NEEDED': return 'No reply needed';
      default: return r.recommended_action;
    }
  }
  const FLAG_TEXT = {
    SUSPICIOUS: 'Looks suspicious — needs a human to review it.',
    PROMPT_INJECTION: 'The email tries to give instructions to the AI. They were ignored.',
    MIXED_INTENT: 'The email contains more than one kind of request.',
    PAST_DATE: 'A date in the email is already in the past.',
    INCOTERM_MODE_MISMATCH: 'The Incoterm does not fit the transport mode.',
    DRAFT_CONTAINS_UNSUPPORTED_CLAIM: 'The AI draft made a claim it cannot support, so a safe template is shown.',
    MULTIPLE_SHIPMENTS: 'The email describes more than one shipment.',
    ATTACHMENT_REFERENCED: 'The email refers to an attachment that this tool cannot read.',
  };
  const LLM_CODES = ['LLM_UNAVAILABLE', 'LLM_AUTH', 'LLM_CREDITS'];
  const GROUPS = {
    dimensions_or_cbm: ['dimensions', 'cbm'],
    invoice_or_transaction: ['invoice_number', 'transaction_reference'],
  };
  const STEPS = [
    ['received', 'Email received'],
    ['router', 'Router agent'],
    ['classified', 'Classified'],
    ['skill', 'Skill loaded'],
    ['agent', 'Skill agent'],
    ['validate', 'Validation'],
    ['draft', 'Draft ready'],
  ];
  const STATUS_LABEL = { pending: 'Pending review', approved: '✓ Approved', rejected: '✕ Rejected' };

  const state = {
    items: [],
    view: DASH,
    run: null,            // the workflow shown in the popup (running, done or failed)
    lastRequest: null,
    busy: false,
    samples: [],
    health: null,
    maxBody: 8000,
    showAll: {},
    drawerId: null,
    rejecting: false,
    justAdded: null,
    prevStats: null,
    lastFocus: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);

  /** Tiny DOM builder. Strings are always inserted as text. */
  function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  /** replaceChildren that ignores null / false entries. */
  function setChildren(el, ...kids) {
    el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
  }

  /* ============================================================ storage */
  function migrateItem(i) {
    return {
      ...i,
      status: i.status === 'approved' || i.status === 'rejected' ? i.status : 'pending',
      decidedAt: i.decidedAt ?? i.approvedAt ?? null,
      rejectReason: i.rejectReason || '',
      trace: Array.isArray(i.trace) ? i.trace : null,
    };
  }
  function loadItems() {
    try {
      const raw = localStorage.getItem(KEY_V2) || localStorage.getItem(KEY_V1);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr.filter((i) => i && i.result && i.result.category).map(migrateItem) : [];
    } catch (e) {
      return [];
    }
  }
  function saveItems() {
    try {
      state.items = state.items.slice(0, MAX_ITEMS);
      localStorage.setItem(KEY_V2, JSON.stringify(state.items));
    } catch (e) { /* storage unavailable: the app keeps working for this session */ }
  }
  let saveTimer = null;
  function saveSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(saveItems, 250); }

  /* ============================================================ helpers */
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
  const byId = (id) => state.items.find((i) => i.id === id);
  const catOf = (id) => CATS.find((c) => c.id === id) || CATS[CATS.length - 1];
  const itemsIn = (cat) => state.items.filter((i) => i.result.category === cat).sort((a, b) => b.createdAt - a.createdAt);
  const modeClass = (mode) => (mode === 'AIR' ? 'chip-air' : mode === 'OCEAN' ? 'chip-ocean' : 'chip-unknown');
  const requiredMissing = (r) => r.missing_information.filter((m) => m.reason === 'required').length;
  const modelLabel = (m) => {
    if (!m) return '';
    if (String(m).startsWith('MOCK')) return 'MOCK';
    const name = String(m).split('/').pop();
    return name.endsWith(':free') ? name.slice(0, -5) : name + ' · paid';
  };
  const REASON_TEXT = {
    provider_error: 'overloaded', rate_limited: 'rate-limited', timeout: 'timed out', network_error: 'network error',
    empty_content: 'empty reply', bad_output: 'unusable reply', invalid_response: 'invalid response',
    skipped_deadline: 'skipped (time limit)',
  };
  const reasonText = (r) => REASON_TEXT[r] || (String(r).startsWith('http_') ? 'HTTP ' + String(r).slice(5) : 'failed');
  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : ms + ' ms');

  function timeAgo(ts) {
    const s = Math.max(0, (Date.now() - ts) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 86400) return Math.floor(s / 3600) + ' h ago';
    return new Date(ts).toLocaleDateString([], { day: 'numeric', month: 'short' });
  }
  function fmtDateTime(ts) {
    const d = new Date(ts);
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ' · ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  let toastTimer = null;
  function toast(message, action) {
    const el = $('#toast');
    setChildren(el, h('span', { text: message }), action ? h('button', { type: 'button', onclick: () => { el.classList.remove('show'); action.fn(); } }, action.label) : null);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), action ? 7000 : 3200);
  }

  /* ============================================================ theme */
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
    $('#themeToggle').setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  }

  /* ============================================================ server status, samples */
  async function loadHealth() {
    const pill = $('#apiStatus');
    // Only show something when there is something to know: mock mode, or a problem.
    const set = (name, text, title) => {
      pill.hidden = !name;
      if (name) { pill.dataset.state = name; pill.lastElementChild.textContent = text; pill.title = title || ''; }
    };
    try {
      const d = await (await fetch('/api/health')).json();
      state.health = d;
      state.maxBody = d.max_body_chars || state.maxBody;
      updateCount();
      if (d.mock) set('mock', 'Mock mode', 'MOCK_LLM=1: answers are canned, OpenRouter is not called.');
      else if (!d.key_configured) set('bad', 'API key missing', 'OPENROUTER_API_KEY is not set on the server.');
      else set(null);
    } catch (e) {
      set('bad', 'Server offline', 'Could not reach the Hermes server.');
    }
    refreshQuota();
  }
  function refreshQuota() {
    const d = state.health;
    $('#quotaLine').textContent = !d || d.mock ? '' : `AI requests today: ${d.ai_calls_today} / ~${d.free_daily_limit}`;
  }

  async function loadSamples() {
    try { state.samples = await (await fetch('/api/samples')).json(); } catch (e) { state.samples = []; }
    const chips = $('#sampleChips');
    const select = $('#edgeSelect');
    for (const s of state.samples) {
      if (s.group === 'test') chips.append(h('button', { class: 'chip', type: 'button', title: s.subject, onclick: () => fillSample(s) }, s.label.split(' · ')[0]));
      else select.append(h('option', { value: s.id }, s.label));
    }
    if (select.options.length === 1) select.hidden = true;
  }
  function fillSample(s) {
    $('#subject').value = s.subject;
    $('#body').value = s.body;
    $('#formError').hidden = true;
    updateCount();
    $('#analyzeBtn').focus();
  }
  function updateCount() {
    const n = $('#body').value.length;
    const el = $('#charCount');
    el.textContent = `${n} / ${state.maxBody}`;
    el.style.color = n > state.maxBody ? 'var(--bad)' : '';
  }

  /* ============================================================ counters (last 24 h + total) */
  function computeStats() {
    const now = Date.now();
    const within = (ts) => ts != null && now - ts < DAY_MS;
    const all = state.items;
    const count = (fn) => all.filter(fn).length;
    return {
      received: { h24: count((i) => within(i.createdAt)), total: all.length },
      pending: { h24: count((i) => i.status === 'pending' && within(i.createdAt)), total: count((i) => i.status === 'pending') },
      approved: { h24: count((i) => i.status === 'approved' && within(i.decidedAt)), total: count((i) => i.status === 'approved') },
      rejected: { h24: count((i) => i.status === 'rejected' && within(i.decidedAt)), total: count((i) => i.status === 'rejected') },
    };
  }
  const STAT_DEFS = [
    ['received', 'Received', 'Emails analysed. Last 24 h = received in the past 24 hours.'],
    ['pending', 'Pending', 'Drafts waiting for a decision. Last 24 h = received in the past 24 hours and still pending.'],
    ['approved', 'Approved', 'Drafts you approved. Last 24 h = approved in the past 24 hours.'],
    ['rejected', 'Rejected', 'Drafts you rejected. Last 24 h = rejected in the past 24 hours.'],
  ];
  function statsEl() {
    const stats = computeStats();
    const prev = state.prevStats;
    const el = h('section', { class: 'stats', 'aria-label': 'Counters' }, STAT_DEFS.map(([kind, label, tip]) => {
      const s = stats[kind];
      const changed = prev && (prev[kind].h24 !== s.h24 || prev[kind].total !== s.total);
      return h('div', { class: 'stat', 'data-kind': kind, 'data-bump': changed ? '1' : null, title: tip },
        h('span', { class: 'stat-label', text: label }),
        h('div', { class: 'stat-nums' },
          h('div', { class: 'stat-num' }, h('span', { class: 'stat-value', text: String(s.h24) }), h('span', { class: 'stat-sub', text: 'Last 24 h' })),
          h('div', { class: 'stat-div' }),
          h('div', { class: 'stat-num total' }, h('span', { class: 'stat-value', text: String(s.total) }), h('span', { class: 'stat-sub', text: 'Total' }))));
    }));
    state.prevStats = stats;
    return el;
  }

  /* ============================================================ workflow model */
  function newSteps() {
    return STEPS.map(([key, label]) => ({ key, label, status: 'pending', detail: '', ms: null }));
  }
  const step = (steps, key) => steps.find((s) => s.key === key);
  function setStep(s, status, detail, ms) {
    s.status = status;
    if (detail !== undefined) s.detail = detail || '';
    if (ms !== undefined) s.ms = ms;
  }

  /** Apply one server event to a run. Step text is kept very short on purpose. */
  function applyEvent(run, e) {
    const S = (k) => step(run.steps, k);
    if (e.cached) run.cached = true;
    switch (e.event) {
      case 'received':
        setStep(S('received'), 'done');
        break;
      case 'router_start':
        setStep(S('router'), 'active', 'picking a model…');
        break;
      case 'model_try': {
        // which model the server is calling right now (router or skill stage)
        setStep(S(e.stage === 'skill' ? 'agent' : 'router'), 'active', 'trying ' + modelLabel(e.model) + '…');
        break;
      }
      case 'model_fail': {
        const st = S(e.stage === 'skill' ? 'agent' : 'router');
        (st.notes = st.notes || []).push(`${modelLabel(e.model)} ${reasonText(e.reason)}`);
        break;
      }
      case 'model_skip': {
        // a model that failed minutes ago (or the free daily limit) is skipped on purpose
        const st = S(e.stage === 'skill' ? 'agent' : 'router');
        const note = e.reason === 'daily_limit' ? 'free models: daily limit used up' : `${modelLabel(e.model)} cooling down`;
        st.notes = st.notes || [];
        if (!st.notes.includes(note)) st.notes.push(note);
        break;
      }
      case 'router_done': {
        setStep(S('router'), 'done', modelLabel(e.model) + (e.single_call ? ' · single call' : ''), e.single_call ? null : e.ms);
        const c = S('classified');
        c.label = 'Classified · ' + catOf(e.category).short;
        setStep(c, 'done', e.confidence);
        run.category = e.category;
        break;
      }
      case 'skill_loaded': {
        const s = S('skill');
        setStep(s, 'done', e.file);
        break;
      }
      case 'skill_start':
        setStep(S('agent'), 'active', e.single_call ? 'same request' : 'picking a model…');
        break;
      case 'skill_done':
        setStep(S('agent'), 'done', e.single_call ? 'same request' : modelLabel(e.model), e.single_call ? null : e.ms);
        setStep(S('validate'), 'active');
        break;
      case 'validation': {
        const v = S('validate');
        setStep(v, e.issues ? 'warn' : 'done', `${e.checks.length} checks · ${e.issues} issue${e.issues === 1 ? '' : 's'}`);
        v.checks = e.checks;
        break;
      }
      case 'done':
        setStep(S('draft'), 'done', 'Ready for review');
        break;
      default:
        break;
    }
  }

  /** Steps for an item: the stored trace, or a rebuilt one for items from older versions. */
  function stepsFromResult(result) {
    const steps = newSteps();
    const m = result.meta || {};
    const st = m.stages || {};
    for (const s of steps) s.status = 'done';
    step(steps, 'router').detail = modelLabel((st.router && st.router.model) || m.router_model || m.model);
    if (st.router) step(steps, 'router').ms = st.router.ms;
    step(steps, 'agent').detail = modelLabel(m.model);
    const c = step(steps, 'classified');
    c.label = 'Classified · ' + catOf(result.category).short;
    c.detail = result.category_confidence || '';
    step(steps, 'skill').detail = catOf(result.category).file;
    if (st.skill) step(steps, 'agent').ms = st.skill.ms;
    const v = step(steps, 'validate');
    if (result.checks) {
      const issues = result.checks.filter((k) => k.status === 'warn' || k.status === 'fail').length;
      v.detail = `${result.checks.length} checks · ${issues} issue${issues === 1 ? '' : 's'}`;
      v.checks = result.checks;
      if (issues) v.status = 'warn';
    }
    return steps;
  }

  function traceFor(item) {
    const steps = item.trace ? JSON.parse(JSON.stringify(item.trace)) : stepsFromResult(item.result);
    const d = step(steps, 'draft');
    d.status = 'done';
    d.label = 'Draft ready';
    d.detail = item.status === 'pending' ? 'Awaiting review' : item.status === 'approved' ? 'Approved' : 'Rejected';
    return steps;
  }

  /* ============================================================ workflow rendering */
  const DOT = { done: '✓', warn: '!', error: '✕', active: '' };

  function flowEl(steps, { vertical = false, decision = null } = {}) {
    return h('ol', { class: 'flow' + (vertical ? ' vertical' : '') }, steps.map((s, i) => {
      const dec = s.key === 'draft' ? decision : null;
      const status = dec ? 'done' : s.status;
      const dot = dec === 'approved' ? '✓' : dec === 'rejected' ? '✕' : status === 'pending' ? String(i + 1) : DOT[status];
      const label = dec === 'approved' ? 'Approved' : dec === 'rejected' ? 'Rejected' : s.label;
      const meta = dec ? '' : [s.detail, s.ms != null ? fmtMs(s.ms) : null].filter(Boolean).join(' · ');
      const notes = (s.notes || []).map((n) => h('div', { class: 'step-note', text: '↳ ' + n }));
      return h('li', { class: 'step', 'data-status': status, 'data-decision': dec },
        h('div', { class: 'step-dot', text: dot }),
        h('div', { class: 'step-title', text: label }),
        meta ? h('div', { class: 'step-meta', text: meta }) : null,
        notes);
    }));
  }

  function checksEl(checks) {
    const ICON = { ok: '✓', info: 'i', warn: '!', fail: '✕' };
    return h('ul', { class: 'checks' }, checks.map((c) =>
      h('li', {}, h('span', { class: 'ck ck-' + c.status, text: ICON[c.status] || '•' }),
        h('div', {}, h('b', { text: c.name }), h('span', { class: 'd', text: c.detail })))));
  }

  /* ============================================================ sidebar, top bar, views */
  function navigate(view) {
    state.view = view === DASH || CATS.some((c) => c.id === view) ? view : DASH;
    try { localStorage.setItem(VIEW_KEY, state.view); } catch (e) { /* ignore */ }
    renderAll();
    window.scrollTo(0, 0);
  }

  function navItem(id, label, items) {
    const pending = items.filter((i) => i.status === 'pending').length;
    const badge = pending ? h('span', { class: 'nav-badge pending', title: `${pending} pending`, text: String(pending) })
      : items.length ? h('span', { class: 'nav-badge', text: String(items.length) }) : null;
    return h('button', { class: 'nav-item', type: 'button', 'aria-current': state.view === id ? 'page' : null, onclick: () => navigate(id) },
      h('span', { text: label }), badge);
  }
  function renderNav() {
    setChildren($('#nav'),
      navItem(DASH, 'Dashboard', state.items),
      h('div', { class: 'nav-label', text: 'Categories' }),
      CATS.map((c) => navItem(c.id, c.short, itemsIn(c.id))));
  }

  function renderTopbar() {
    $('#pageTitle').textContent = state.view === DASH ? 'Dashboard' : state.view;
    document.title = (state.view === DASH ? 'Dashboard' : catOf(state.view).short) + ' · Hermes Email Assistant';
  }

  function emptyEl(title) {
    return h('div', { class: 'empty' },
      h('strong', { text: title }),
      h('button', { class: 'btn btn-primary', type: 'button', onclick: openComposer }, 'Send email'));
  }

  const catChip = (id) => h('span', { class: 'chip chip-sm chip-soft', text: catOf(id).short });

  function historyRow(item, withCategory) {
    const r = item.result;
    const reqMissing = requiredMissing(r);
    return h('button', {
      class: 's-' + item.status + ' hrow' + (item.id === state.justAdded ? ' flash' : ''), type: 'button',
      onclick: () => openDrawer(item.id), 'aria-label': `${item.subject || 'email'} — ${STATUS_LABEL[item.status]}. Open`,
    },
    h('span', { class: 'hrow-bar' }),
    h('span', { class: 'hrow-main' },
      h('span', { class: 'hrow-subject', text: item.subject || '(no subject)' }),
      h('span', { class: 'hrow-meta' },
        withCategory ? h('span', { class: 'chip chip-sm chip-cat', text: catOf(r.category).short }) : null,
        h('span', { text: timeAgo(item.createdAt) }),
        r.mode ? h('span', { class: 'chip chip-sm ' + modeClass(r.mode), text: r.mode + (r.submode ? ' · ' + r.submode : '') }) : null,
        h('span', { text: r.information_complete ? 'complete' : `${reqMissing} missing` }),
        r.flags.length ? h('span', { class: 'chip chip-sm chip-bad', text: '⚑ ' + r.flags.length }) : null,
        r.meta && r.meta.mock ? h('span', { class: 'chip chip-sm chip-soft', text: 'mock' }) : null)),
    h('span', { class: 'hrow-status', text: STATUS_LABEL[item.status] }),
    h('span', { class: 'hrow-go', 'aria-hidden': 'true', text: '›' }));
  }

  function dashboardView() {
    const nodes = [statsEl()];
    const latest = [...state.items].sort((a, b) => b.createdAt - a.createdAt).slice(0, LATEST_SIZE);
    if (!latest.length) {
      nodes.push(emptyEl('No emails yet'));
    } else {
      nodes.push(h('section', { class: 'list' },
        h('div', { class: 'section-head' }, h('h2', { text: 'Latest emails' }),
          state.items.length > latest.length ? h('span', { class: 'muted small', text: `${latest.length} of ${state.items.length}` }) : null),
        latest.map((i) => historyRow(i, true))));
    }
    return nodes;
  }

  function categoryView(cat) {
    const list = itemsIn(cat.id);
    if (!list.length) return [emptyEl(`No ${cat.short.toLowerCase()} emails yet`)];
    const count = (st) => list.filter((i) => i.status === st).length;
    const latest = list[0];
    const all = !!state.showAll[cat.id];
    const rows = all ? list : list.slice(0, HISTORY_SIZE);
    return [
      h('div', { class: 'mini-counts' },
        h('span', { class: 'chip chip-warn' }, 'Pending ', h('b', { text: String(count('pending')) })),
        h('span', { class: 'chip chip-ok' }, 'Approved ', h('b', { text: String(count('approved')) })),
        h('span', { class: 'chip chip-bad' }, 'Rejected ', h('b', { text: String(count('rejected')) }))),
      h('div', { class: 'flow-card' },
        h('div', { class: 'flow-head' },
          h('div', { class: 'flow-title' }, h('span', { class: 'eyebrow', text: 'Latest workflow' }), h('strong', { text: latest.subject || '(no subject)' })),
          h('div', { class: 'flow-actions' },
            h('span', { class: 'muted small', text: timeAgo(latest.createdAt) }),
            h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => openDrawer(latest.id) }, latest.status === 'pending' ? 'Review' : 'Open'))),
        flowEl(traceFor(latest), { decision: latest.status === 'pending' ? null : latest.status })),
      h('section', { class: 'list' },
        h('div', { class: 'section-head' },
          h('h2', { text: 'History' }),
          list.length > HISTORY_SIZE
            ? h('button', { class: 'link-btn', type: 'button', onclick: () => { state.showAll[cat.id] = !all; renderView(); } }, all ? 'Show last 5' : `Show all ${list.length}`)
            : h('span', { class: 'muted small', text: `Last ${Math.min(HISTORY_SIZE, list.length)}` })),
        rows.map((i) => historyRow(i, false))),
    ];
  }

  function renderView() {
    setChildren($('#view'), state.view === DASH ? dashboardView() : categoryView(catOf(state.view)));
  }
  function renderAll() {
    renderNav();
    renderTopbar();
    renderView();
    updateSendButton();
  }

  /* ============================================================ overlays (popup + drawer) */
  function showOverlay(el) {
    if ($('#composerModal').hidden && $('#drawer').hidden) state.lastFocus = document.activeElement;
    el.hidden = false;
    document.body.classList.add('no-scroll');
  }
  function hideOverlay(el) {
    el.hidden = true;
    if ($('#composerModal').hidden && $('#drawer').hidden) {
      document.body.classList.remove('no-scroll');
      if (state.lastFocus && state.lastFocus.focus) { try { state.lastFocus.focus(); } catch (e) { /* ignore */ } }
    }
  }
  function trapFocus(e, root) {
    const f = [...root.querySelectorAll('button:not([disabled]),input:not([disabled]),select,textarea,summary,[tabindex]:not([tabindex="-1"])')]
      .filter((el) => el.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /* ---------------- popup: form <-> workflow */
  function clearForm() {
    $('#subject').value = '';
    $('#body').value = '';
    $('#edgeSelect').value = '';
    $('#formError').hidden = true;
    updateCount();
  }
  function renderComposer() {
    const showRun = !!state.run;
    $('#composeForm').hidden = showRun;
    $('#runView').hidden = !showRun;
    if (showRun) renderRunView();
  }
  function openComposer() {
    hideBanner();
    if (state.run && state.run.status !== 'running') {
      if (state.run.status === 'done') clearForm();
      state.run = null;
    }
    showOverlay($('#composerModal'));
    renderComposer();
    refreshQuota();
    if (!state.run) $('#subject').focus();
  }
  function closeComposer() { hideOverlay($('#composerModal')); }

  function goDashboard() {
    closeComposer();
    if (state.run && state.run.status === 'done') state.run = null;
    navigate(DASH);
  }
  function reviewNow(id) {
    closeComposer();
    state.run = null;
    navigate(DASH);
    openDrawer(id);
  }
  function analyseAnother() {
    state.run = null;
    clearForm();
    renderComposer();
    $('#subject').focus();
  }
  function editEmail() {
    state.run = null;
    renderComposer();
    $('#subject').focus();
  }

  function renderRunView() {
    const run = state.run;
    if (!run) return;
    const kids = [
      h('div', { class: 'run-subject' },
        h('span', { class: 'eyebrow', text: run.status === 'running' ? 'Analysing' : run.status === 'error' ? 'Stopped' : 'Done' }),
        h('strong', { text: run.subject || '(no subject)' })),
      flowEl(run.steps, { vertical: true }),
    ];
    if (run.status === 'done') {
      const item = byId(run.itemId);
      if (item) {
        const r = item.result;
        kids.push(h('div', { class: 'run-summary' },
          h('h3', { text: `Draft ready in ${catOf(r.category).short}` }),
          h('div', { class: 'chip-row' },
            r.mode ? h('span', { class: 'chip ' + modeClass(r.mode), text: r.mode + (r.submode ? ' · ' + r.submode : '') }) : null,
            h('span', { class: 'chip ' + (r.information_complete ? 'chip-ok' : 'chip-warn'), text: r.information_complete ? 'Info complete' : `${requiredMissing(r)} details missing` }),
            r.draft_reply.source === 'none' ? h('span', { class: 'chip chip-no', text: 'Flagged' }) : null),
          h('div', { class: 'run-actions' },
            h('button', { class: 'btn btn-primary', type: 'button', onclick: () => reviewNow(item.id) }, 'Review draft'),
            h('button', { class: 'btn btn-ghost', type: 'button', onclick: goDashboard }, 'Go to dashboard'),
            h('button', { class: 'btn btn-ghost', type: 'button', onclick: analyseAnother }, 'Analyse another'))));
      }
    } else if (run.status === 'error') {
      kids.push(errorEl(run.error, true));
    }
    setChildren($('#runView'), kids);
  }

  /* ---------------- drawer */
  const statusChip = (item) => h('span', {
    class: 'chip ' + (item.status === 'approved' ? 'chip-ok' : item.status === 'rejected' ? 'chip-bad' : 'chip-warn'),
    text: STATUS_LABEL[item.status],
  });

  function openDrawer(id) {
    const item = byId(id);
    if (!item) return;
    state.drawerId = id;
    state.rejecting = false;
    renderDrawer();
    showOverlay($('#drawer'));
    $('#drawerBody').scrollTop = 0;
    $('.drawer-head button', $('#drawer')).focus();
  }
  function closeDrawer() { state.drawerId = null; state.rejecting = false; hideOverlay($('#drawer')); }

  function checkChip(ok, yes, no) {
    return h('span', { class: 'chip ' + (ok ? 'chip-ok' : 'chip-no') }, ok ? '✓ ' : '✕ ', ok ? yes : no);
  }

  function renderDrawer() {
    const item = byId(state.drawerId);
    if (!item) return;
    const r = item.result;
    setChildren($('#drawerHead'),
      h('div', { class: 'row' },
        h('div', { class: 'chip-row' }, h('span', { class: 'chip chip-cat', text: catOf(r.category).short }), statusChip(item)),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: closeDrawer }, '×')),
      h('h2', { id: 'drawerTitle', text: item.subject || '(no subject)' }),
      h('span', { class: 'muted small', text: `${r.sender_name ? 'From ' + r.sender_name + ' · ' : ''}${fmtDateTime(item.createdAt)}` }));

    const decided = item.status !== 'pending';
    const d = r.draft_reply;
    const sections = [];

    // 1. classification and mode (the brief's order: classification -> mode -> fields -> missing -> reply)
    const chips = [
      h('span', { class: 'chip chip-cat', text: r.category }),
      h('span', { class: 'chip chip-soft', text: `${r.category_confidence} confidence` }),
    ];
    if (r.mode) {
      chips.push(h('span', { class: 'chip ' + modeClass(r.mode), text: 'Mode: ' + r.mode + (r.submode ? ' · ' + r.submode : '') }));
      chips.push(h('span', { class: 'mode-note', text: r.mode_evidence ? `from “${r.mode_evidence}”` : 'no explicit air/ocean wording' }));
    }
    if (r.meta && r.meta.mock) chips.push(h('span', { class: 'chip chip-warn', text: 'MOCK' }));
    sections.push(h('div', { class: 'sec' },
      h('h3', { text: 'Classification' }),
      h('div', { class: 'chip-row' }, chips),
      r.category_reason ? h('p', { class: 'muted small', style: 'margin-top:8px', text: r.category_reason }) : null,
      h('div', { class: 'status-chips' },
        checkChip(r.information_complete, 'Information complete', `Incomplete (${requiredMissing(r)} required missing)`),
        h('span', { class: 'chip chip-soft', text: 'Next: ' + nextStep(r) }))));

    // draft
    const srcChip = h('span', {
      class: 'chip ' + (d.source === 'ai' ? 'chip-ok' : d.source === 'template' ? 'chip-warn' : 'chip-no'),
      text: d.source === 'ai' ? 'AI draft' : d.source === 'template' ? 'Template' : 'No draft',
    });
    let draftBox;
    if (d.source === 'none') {
      draftBox = h('div', { class: 'no-draft', text: (d.notes && d.notes[0]) || 'No reply was drafted for this email.' });
    } else {
      const subj = h('input', { id: 'draftSubject', class: 'input', type: 'text', value: item.draftSubject || '', 'aria-label': 'Reply subject' });
      const bodyTa = h('textarea', { id: 'draftBody', class: 'textarea mono', rows: '12', 'aria-label': 'Reply body' });
      bodyTa.value = item.draftBody || '';
      bodyTa.rows = Math.min(22, Math.max(8, bodyTa.value.split('\n').length + 1));
      if (decided) { subj.readOnly = true; bodyTa.readOnly = true; }
      const onEdit = () => { item.draftSubject = subj.value; item.draftBody = bodyTa.value; saveSoon(); };
      subj.addEventListener('input', onEdit);
      bodyTa.addEventListener('input', onEdit);
      draftBox = h('div', { style: 'display:grid;gap:8px' }, subj, bodyTa);
    }
    const replySection = h('div', { class: 'sec' },
      h('div', { class: 'sec-head' }, h('h3', { text: 'Suggested reply' }), srcChip),
      h('div', { class: 'draft-notes', text: (d.notes || []).join(' ') }),
      draftBox);

    // 2. extracted fields, 3. missing / unclear / conflicting, 4. the reply
    sections.push(h('div', { class: 'panel' },
      h('div', { class: 'sec-head' }, h('h3', { text: 'Extracted fields' }),
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: () => copyJson(item.id) }, 'Copy JSON')),
      h('table', { class: 'fields-table' }, h('tbody', {}, fieldRows(r)))));
    sections.push(h('div', { class: 'panel' }, h('h3', { text: 'Missing, unclear or conflicting' }), renderAttention(r)));
    sections.push(replySection);

    const steps = traceFor(item);
    const validate = step(steps, 'validate');
    sections.push(h('div', { class: 'sec' }, h('h3', { text: 'Workflow' }),
      flowEl(steps, { vertical: true, decision: decided ? item.status : null }),
      validate && validate.checks ? checksEl(validate.checks) : null));
    sections.push(h('details', { class: 'original' }, h('summary', { text: 'Original email' }), h('pre', { text: `Subject: ${item.subject}\n\n${item.body}` })));
    sections.push(metaEl(r));
    setChildren($('#drawerBody'), sections);
    renderDrawerFoot();
  }

  function metaEl(r) {
    const m = r.meta || {};
    const log = m.attempt_log || [];
    const bits = [
      m.mock ? 'Mock mode' : m.router_model && m.router_model !== m.model ? `Router: ${modelLabel(m.router_model)} · Skill agent: ${modelLabel(m.model)}` : `Model: ${modelLabel(m.model)}`,
      m.cached ? 'from cache' : null,
      m.latency_ms != null ? `${(m.latency_ms / 1000).toFixed(1)} s` : null,
    ].filter(Boolean).join(' · ');
    return h('div', { class: 'meta' }, h('span', { text: bits }),
      log.some((a) => a.reason !== 'ok')
        ? h('details', { class: 'metadet' }, h('summary', { text: `Model attempts (${log.length})` }),
            h('ul', {}, log.map((a) => h('li', { text: `${a.stage ? a.stage + ': ' : ''}${modelLabel(a.model)} — ${a.reason}${a.status ? ' (HTTP ' + a.status + ')' : ''} · ${a.ms} ms` }))))
        : null);
  }

  function renderDrawerFoot() {
    const item = byId(state.drawerId);
    if (!item) return;
    const foot = $('#drawerFoot');
    const none = item.result.draft_reply.source === 'none';
    const copyBtn = none ? null : h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => copyDraft(item.id) }, 'Copy');

    if (item.status !== 'pending') {
      setChildren(foot,
        h('div', { class: 'grow' },
          h('strong', { text: `${item.status === 'approved' ? '✓ Approved' : '✕ Rejected'} · ${fmtDateTime(item.decidedAt)}` }),
          item.status === 'rejected' && item.rejectReason ? h('div', { class: 'muted small', text: item.rejectReason }) : null),
        copyBtn,
        h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => reopen(item.id) }, 'Reopen'));
      return;
    }
    if (state.rejecting) {
      const reason = h('input', { class: 'input', type: 'text', maxlength: '200', placeholder: 'Reason (optional)', 'aria-label': 'Reason for rejecting' });
      reason.addEventListener('keydown', (e) => { if (e.key === 'Enter') decide(item.id, 'rejected', reason.value.trim()); });
      setChildren(foot, h('div', { class: 'reason' }, reason,
        h('div', { style: 'display:flex;gap:8px;justify-content:flex-end' },
          h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => { state.rejecting = false; renderDrawerFoot(); } }, 'Cancel'),
          h('button', { class: 'btn btn-reject', type: 'button', onclick: () => decide(item.id, 'rejected', reason.value.trim()) }, 'Confirm reject'))));
      reason.focus();
      return;
    }
    setChildren(foot,
      h('button', { class: 'btn btn-reject', type: 'button', onclick: () => { state.rejecting = true; renderDrawerFoot(); } }, 'Reject'),
      copyBtn,
      h('span', { class: 'grow' }),
      h('button', { class: 'btn btn-approve', type: 'button', onclick: () => decide(item.id, 'approved') }, none ? 'Mark reviewed' : 'Approve'));
  }

  /* ============================================================ fields + attention */
  function fieldRows(r) {
    const missing = new Set(r.missing_information.map((m) => m.field));
    const either = new Set();
    for (const [g, keys] of Object.entries(GROUPS)) if (missing.has(g)) keys.forEach((k) => either.add(k));
    if (missing.has('container_type')) missing.add('container');
    return Object.entries(r.fields).map(([key, f]) => {
      const isEither = !f.found && either.has(key);
      const isMissing = !f.found && (missing.has(key) || isEither);
      const value = f.found ? f.value + (f.unit ? ' ' + f.unit : '') : isMissing ? 'Missing' : '—';
      return h('tr', { class: f.found ? '' : 'row-missing' },
        h('td', { class: 'f-label', text: f.label }),
        h('td', {},
          h('span', { class: 'f-value', text: value }),
          f.note ? h('span', { class: 'chip chip-warn f-note', text: f.note }) : null,
          f.found && f.evidence && f.evidence !== f.value ? h('span', { class: 'f-evidence', text: `“${f.evidence}”` }) : null),
        h('td', { class: 'f-state ' + (f.found ? 'found' : isMissing ? 'missing' : 'none'), text: f.found ? '✓ found' : isEither ? '✕ either one' : isMissing ? '✕ missing' : '' }));
    });
  }

  function attentionBlock(title, list, renderLi) {
    return h('div', { class: 'att-block' }, h('h4', { text: title }), h('ul', { class: 'att-list' }, list.map(renderLi)));
  }
  function renderAttention(r) {
    const blocks = [];
    if (r.missing_information.length) {
      blocks.push(attentionBlock('Missing', r.missing_information, (m) =>
        h('li', {}, m.label, m.reason === 'recommended' ? h('span', { class: 'tag', text: 'recommended' }) : null)));
    }
    if (r.conflicts.length) blocks.push(attentionBlock('Conflicts', r.conflicts, (t) => h('li', { text: t })));
    if (r.ambiguities.length) blocks.push(attentionBlock('Unclear', r.ambiguities, (t) => h('li', { text: t })));
    if (r.customer_questions && r.customer_questions.length) {
      blocks.push(attentionBlock('Customer asks', r.customer_questions, (t) => h('li', { text: t })));
    }
    if (r.removed_unsupported.length) blocks.push(attentionBlock('Removed by validation', r.removed_unsupported, (t) => h('li', { text: t })));
    if (r.flags.length) blocks.push(attentionBlock('Flags', r.flags, (f) => h('li', { text: FLAG_TEXT[f] || f })));
    if (r.mode_note) blocks.push(attentionBlock('Mode', [r.mode_note], (t) => h('li', { text: t })));
    if (r.notes && r.notes.length) blocks.push(attentionBlock('Note', r.notes, (t) => h('li', { text: t })));
    return h('div', {}, blocks.length ? blocks : h('p', { class: 'att-clear', text: '✓ Nothing to flag' }));
  }

  /* ============================================================ decisions */
  function decide(id, status, reason) {
    const item = byId(id);
    if (!item || item.status !== 'pending') return;
    item.status = status;
    item.decidedAt = Date.now();
    item.rejectReason = reason || '';
    saveItems();
    closeDrawer();
    state.justAdded = id;
    renderAll();
    setTimeout(() => { if (state.justAdded === id) state.justAdded = null; }, 2000);
    toast(status === 'approved' ? 'Approved ✓' : 'Rejected ✕', { label: 'Undo', fn: () => reopen(id) });
  }
  function reopen(id) {
    const item = byId(id);
    if (!item) return;
    item.status = 'pending';
    item.decidedAt = null;
    item.rejectReason = '';
    saveItems();
    renderAll();
    if (state.drawerId === id) renderDrawer();
    toast('Moved back to pending.');
  }
  async function copyText(text, message) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = h('textarea', { style: 'position:fixed;opacity:0' });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (err) { /* ignore */ }
      ta.remove();
    }
    toast(message);
  }
  function copyDraft(id) {
    const item = byId(id);
    if (item) copyText(`Subject: ${item.draftSubject}\n\n${item.draftBody}`, 'Reply copied.');
  }
  /** The extraction as structured data a team (or another system) can use. */
  function structuredJson(item) {
    const r = item.result;
    const fields = {};
    for (const [key, f] of Object.entries(r.fields)) fields[key] = f.found ? { value: f.value, unit: f.unit, evidence: f.evidence } : null;
    return {
      subject: item.subject,
      category: r.category,
      confidence: r.category_confidence,
      mode: r.mode,
      submode: r.submode,
      fields,
      missing_information: r.missing_information.map((m) => ({ field: m.field, ask: m.label, reason: m.reason })),
      ambiguities: r.ambiguities,
      conflicts: r.conflicts,
      flags: r.flags,
      recommended_action: r.recommended_action,
      information_complete: r.information_complete,
      draft_reply: { subject: item.draftSubject, body: item.draftBody },
    };
  }
  function copyJson(id) {
    const item = byId(id);
    if (item) copyText(JSON.stringify(structuredJson(item), null, 2), 'JSON copied.');
  }
  function resetAll() {
    if (!state.items.length) return;
    if (!confirm('Delete all emails, drafts and counters stored in this browser?')) return;
    state.items = [];
    state.run = null;
    saveItems();
    closeDrawer();
    renderAll();
    toast('Data cleared.');
  }

  /* ============================================================ analysis (streaming) */
  function netError(e) {
    return {
      kind: 'network', code: 'NETWORK', attempts: [],
      message: e && e.name === 'AbortError'
        ? 'The request took longer than 2.5 minutes and was cancelled.'
        : 'Could not reach the Hermes server. If it is hosted on a free plan it may be waking up — wait a minute and retry.',
    };
  }

  async function streamAnalyze(subject, body, fresh, onEvent) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 150000);
    try {
      let res;
      try {
        res = await fetch('/api/analyze/stream', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ subject, body, fresh }), signal: ctrl.signal,
        });
      } catch (e) { throw netError(e); }
      if (!res.ok) {
        let data = null;
        try { data = await res.json(); } catch (e) { /* not JSON */ }
        const err = (data && data.error) || {};
        throw { kind: 'api', code: err.code || 'HTTP_' + res.status, message: err.message || `The server answered with HTTP ${res.status}.`, attempts: err.attempts || [] };
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let finished = false;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim();
            buf = buf.slice(nl + 1);
            if (!line) continue;
            let ev;
            try { ev = JSON.parse(line); } catch (e) { continue; }
            if (ev.event === 'done' || ev.event === 'error') finished = true;
            onEvent(ev);
          }
        }
      } catch (e) { if (e && e.kind) throw e; throw netError(e); }
      if (!finished) throw { kind: 'network', code: 'NETWORK', message: 'The connection closed before the workflow finished.', attempts: [] };
    } finally {
      clearTimeout(timer);
    }
  }

  function updateSendButton() {
    const btn = $('#sendBtn');
    btn.classList.toggle('is-busy', state.busy);
    $('#sendLabel').textContent = state.busy ? 'Analysing' : 'Send email';
  }

  async function startAnalysis(subject, body, opts = {}) {
    if (state.busy) return;
    hideBanner();
    state.busy = true;
    state.lastRequest = { subject, body, opts };
    const run = { subject, body, steps: newSteps(), category: null, status: 'running', startedAt: Date.now(), cached: false, itemId: null };
    state.run = run;
    if ($('#composerModal').hidden) showOverlay($('#composerModal'));
    renderComposer();
    updateSendButton();

    const onEvent = (e) => {
      if (e.event === 'ping') return;
      if (e.event === 'error') { failRun(run, e); return; }
      applyEvent(run, e);
      if (e.event === 'done') { finishRun(run, e.result); return; }
      renderRunView();
    };

    try {
      await streamAnalyze(subject, body, !!opts.fresh, onEvent);
    } catch (err) {
      if (run.status !== 'error' && run.status !== 'done') failRun(run, err);
    } finally {
      state.busy = false;
      updateSendButton();
      loadHealth();
    }
  }

  function finishRun(run, result) {
    run.status = 'done';
    const item = {
      id: uid(), createdAt: run.startedAt, subject: run.subject, body: run.body, result,
      draftSubject: result.draft_reply.subject, draftBody: result.draft_reply.body,
      status: 'pending', decidedAt: null, rejectReason: '',
      trace: JSON.parse(JSON.stringify(run.steps)),
    };
    run.itemId = item.id;
    state.items.unshift(item);
    state.justAdded = item.id;
    saveItems();
    renderAll();
    setTimeout(() => { if (state.justAdded === item.id) state.justAdded = null; }, 2500);
    if ($('#composerModal').hidden) {
      toast(`Draft ready in ${catOf(result.category).short}`, { label: 'Open', fn: () => { state.run = null; navigate(DASH); openDrawer(item.id); } });
    } else {
      renderRunView();
    }
  }

  function failRun(run, info) {
    run.status = 'error';
    run.error = info;
    const key = info.stage === 'router' || info.stage === 'single' ? 'router'
      : info.stage === 'skill' ? 'agent'
        : (run.steps.find((s) => s.status === 'active') || run.steps[0]).key;
    setStep(step(run.steps, key), 'error', '');
    if ($('#composerModal').hidden) showBanner(info);
    else renderRunView();
  }

  /* ---------------- errors */
  function hideBanner() { $('#errorBanner').hidden = true; }
  function showBanner(err) {
    setChildren($('#errorBanner'), errorEl(err, false));
    $('#errorBanner').hidden = false;
  }
  function errorEl(err, inModal) {
    const isLLM = LLM_CODES.includes(err.code);
    const title = isLLM ? 'OpenRouter API is not working'
      : err.kind === 'network' ? 'The Hermes server is not reachable'
        : err.code === 'RATE_LIMITED' ? 'Too many requests'
          : 'Something went wrong';
    const where = isLLM && err.stage ? `Stopped at the ${err.stage === 'skill' ? 'Skill agent' : 'Router agent'} step.` : null;
    return h('div', { class: inModal ? 'banner run-error' : 'run-error' },
      h('h3', { text: '⚠ ' + title }),
      h('p', { text: err.message }),
      where ? h('p', { class: 'small', text: where }) : null,
      err.attempts && err.attempts.length
        ? h('details', {},
            h('summary', { text: `Details (${err.attempts.length} attempt${err.attempts.length > 1 ? 's' : ''})` }),
            h('ul', {}, err.attempts.map((a) =>
              h('li', { text: `${a.stage ? a.stage + ': ' : ''}${a.model} — ${a.reason}${a.status ? ' (HTTP ' + a.status + ')' : ''}${a.detail ? ': ' + a.detail : ''} · ${a.ms} ms` }))))
        : null,
      h('div', { class: 'banner-actions' },
        h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: retryLast }, 'Retry'),
        inModal
          ? h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: editEmail }, 'Edit email')
          : h('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: hideBanner }, 'Dismiss')));
  }
  function retryLast() {
    const last = state.lastRequest;
    if (!last) return;
    state.run = null;
    hideBanner();
    startAnalysis(last.subject, last.body, last.opts);
  }

  /* ---------------- popup submit */
  function onAnalyzeClick() {
    const subject = $('#subject').value.trim();
    const body = $('#body').value.trim();
    const errEl = $('#formError');
    errEl.hidden = true;
    if (!subject && !body) {
      errEl.textContent = 'Enter a subject or body first.';
      errEl.hidden = false;
      return;
    }
    if (body.length > state.maxBody) {
      errEl.textContent = `The body is too long (max ${state.maxBody} characters).`;
      errEl.hidden = false;
      return;
    }
    startAnalysis(subject, body, { fresh: $('#freshChk').checked });
  }

  /* ============================================================ init */
  function init() {
    state.items = loadItems();
    let view = null;
    try { view = localStorage.getItem(VIEW_KEY); } catch (e) { /* ignore */ }
    state.view = view === DASH || CATS.some((c) => c.id === view) ? view : DASH;

    $('#themeToggle').addEventListener('click', () => applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'));
    applyTheme(document.documentElement.getAttribute('data-theme') || 'light');

    $('#sendBtn').addEventListener('click', openComposer);
    $('#analyzeBtn').addEventListener('click', onAnalyzeClick);
    $('#clearBtn').addEventListener('click', () => { clearForm(); $('#subject').focus(); });
    for (const el of [$('#subject'), $('#body')]) {
      el.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') onAnalyzeClick(); });
    }
    $('#body').addEventListener('input', updateCount);
    $('#edgeSelect').addEventListener('change', (e) => {
      const s = state.samples.find((x) => x.id === e.target.value);
      if (s) fillSample(s);
    });
    $('#resetBtn').addEventListener('click', resetAll);

    document.addEventListener('click', (e) => {
      const closer = e.target.closest('[data-close]');
      if (!closer) return;
      if (closer.dataset.close === 'composer') closeComposer();
      else if (closer.dataset.close === 'drawer') closeDrawer();
    });
    document.addEventListener('keydown', (e) => {
      const drawerOpen = !$('#drawer').hidden;
      const modalOpen = !$('#composerModal').hidden;
      if (e.key === 'Escape') {
        if (drawerOpen) closeDrawer(); else if (modalOpen) closeComposer();
      } else if (e.key === 'Tab' && (drawerOpen || modalOpen)) {
        trapFocus(e, drawerOpen ? $('.drawer') : $('.modal'));
      }
    });

    renderAll();
    updateCount();
    loadHealth();
    loadSamples();
    // keep "x min ago" and the sliding 24 h window fresh
    setInterval(() => { if (!state.busy) renderView(); }, 30000);
  }

  init();
})();
