/* ─── app.js ─── CodeDebug AI Frontend Logic ─── */

// ─── CodeMirror Setup ───────────────────────────
const LANG_MODES = {
  python: 'python', javascript: 'javascript', typescript: 'javascript',
  java: 'text/x-java', cpp: 'text/x-c++src', c: 'text/x-csrc',
  csharp: 'text/x-csharp', go: 'text/x-go', rust: 'text/x-rustsrc',
  php: 'application/x-httpd-php', ruby: 'ruby', sql: 'sql'
};

const editor = CodeMirror.fromTextArea(document.getElementById('codeEditor'), {
  theme: 'dracula',
  lineNumbers: true,
  matchBrackets: true,
  autoCloseBrackets: true,
  autoRefresh: true,
  mode: 'python',
  indentUnit: 4,
  tabSize: 4,
  indentWithTabs: false,
  lineWrapping: false,
  extraKeys: { 'Ctrl-Enter': () => analyzeCode() }
});

let fixedEditor = null;

// ─── State ──────────────────────────────────────
let currentLanguage = 'python';
let isAnalyzing = false;
let errorLineMarks = [];
let examplesData = [];

// ─── DOM References ─────────────────────────────
const $ = id => document.getElementById(id);
const analyzeBtn   = $('analyzeBtn');
const btnLoader    = $('btnLoader');
const btnLabel     = analyzeBtn.querySelector('.btn-label');
const btnIcon      = analyzeBtn.querySelector('.btn-icon');
const langSelect   = $('languageSelect');
const lineCount    = $('lineCount');
const charCount    = $('charCount');
const emptyState   = $('emptyState');
const loadingState = $('loadingState');
const resultsWrap  = $('resultsWrap');
const reportTabs   = $('reportTabs');
const aiStatus     = $('aiStatus');
const toast        = $('toast');

// ─── Init ────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  loadExamples();
  updateCounts();
  initTheme();
  editor.on('change', updateCounts);
});

// ─── Health Check ────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    const d = await r.json();
    const dot  = aiStatus.querySelector('.status-dot');
    const text = aiStatus.querySelector('.status-text');
    if (d.ai_available) {
      dot.className = 'status-dot online';
      text.textContent = 'AI Active';
    } else {
      dot.className = 'status-dot offline';
      text.textContent = 'Static Mode';
    }
  } catch {
    aiStatus.querySelector('.status-text').textContent = 'Offline';
  }
}

// ─── Load Examples ───────────────────────────────
async function loadExamples() {
  try {
    const r = await fetch('/api/examples');
    const d = await r.json();
    examplesData = d.examples;
    const chips = $('examplesChips');
    chips.innerHTML = '';
    d.examples.forEach(ex => {
      const chip = document.createElement('button');
      chip.className = 'chip';
      chip.textContent = ex.title;
      chip.onclick = () => loadExample(ex);
      chips.appendChild(chip);
    });
  } catch (e) {
    console.warn('Could not load examples:', e);
  }
}

function loadExample(ex) {
  langSelect.value = ex.language;
  currentLanguage = ex.language;
  editor.setOption('mode', LANG_MODES[ex.language] || ex.language);
  editor.setValue(ex.code);
  editor.focus();
  showToast(`Loaded: ${ex.title}`);
}

// ─── Update Counts ───────────────────────────────
function updateCounts() {
  const code = editor.getValue();
  const lines = code.split('\n').length;
  lineCount.textContent = `${lines} line${lines !== 1 ? 's' : ''}`;
  charCount.textContent = `${code.length} chars`;
}

// ─── Language Change ─────────────────────────────
langSelect.addEventListener('change', () => {
  currentLanguage = langSelect.value;
  editor.setOption('mode', LANG_MODES[currentLanguage] || currentLanguage);
});

// ─── Clear & Copy ────────────────────────────────
$('clearBtn').addEventListener('click', () => {
  editor.setValue('');
  clearHighlights();
  showEmptyState();
  showToast('Editor cleared');
});

$('copyBtn').addEventListener('click', () => {
  navigator.clipboard.writeText(editor.getValue());
  showToast('Code copied to clipboard!');
});

$('copyFixBtn')?.addEventListener('click', () => {
  if (fixedEditor) {
    navigator.clipboard.writeText(fixedEditor.getValue());
    showToast('Fixed code copied!');
  }
});

// ─── Theme Toggle ────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  if (saved === 'light') document.body.classList.add('light');
  $('themeToggle').textContent = saved === 'light' ? '☀️' : '🌙';
}

$('themeToggle').addEventListener('click', () => {
  document.body.classList.toggle('light');
  const isLight = document.body.classList.contains('light');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  $('themeToggle').textContent = isLight ? '☀️' : '🌙';
});

// ─── Tab Switching ───────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const target = $(`tab-${tab.dataset.tab}`);
    if (target) target.classList.add('active');
    // Refresh fixed editor layout
    if (tab.dataset.tab === 'fix' && fixedEditor) fixedEditor.refresh();
  });
});

// ─── Analyze ─────────────────────────────────────
analyzeBtn.addEventListener('click', analyzeCode);

async function analyzeCode() {
  if (isAnalyzing) return;
  const code = editor.getValue().trim();
  if (!code) { showToast('⚠️ Please enter some code first!'); return; }

  isAnalyzing = true;
  setAnalyzing(true);
  clearHighlights();
  showLoadingState();
  animateLoadingSteps();

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        language: currentLanguage,
        context: $('contextInput').value.trim()
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Analysis failed');
    renderResults(data, code);
  } catch (err) {
    showToast(`❌ Error: ${err.message}`);
    showEmptyState();
  } finally {
    isAnalyzing = false;
    setAnalyzing(false);
  }
}

function setAnalyzing(on) {
  analyzeBtn.disabled = on;
  btnLoader.style.display = on ? 'block' : 'none';
  btnIcon.style.display = on ? 'none' : 'inline';
  btnLabel.textContent = on ? 'Analyzing…' : 'Analyze Code';
}

// ─── Loading Steps Animation ─────────────────────
let stepTimers = [];
function animateLoadingSteps() {
  stepTimers.forEach(clearTimeout);
  stepTimers = [];
  const steps = ['step1','step2','step3','step4'];
  steps.forEach(id => { const el = $(id); if(el){el.className='step';} });
  steps.forEach((id, i) => {
    const t = setTimeout(() => {
      steps.slice(0,i).forEach(prev => { const el=$(prev); if(el) el.className='step done'; });
      const el=$(id); if(el) el.className='step active';
    }, i * 700);
    stepTimers.push(t);
  });
}

// ─── State Transitions ───────────────────────────
function showEmptyState() {
  emptyState.style.display = 'flex';
  loadingState.style.display = 'none';
  resultsWrap.style.display = 'none';
  reportTabs.style.display = 'none';
}
function showLoadingState() {
  emptyState.style.display = 'none';
  loadingState.style.display = 'flex';
  resultsWrap.style.display = 'none';
  reportTabs.style.display = 'none';
}
function showResults() {
  emptyState.style.display = 'none';
  loadingState.style.display = 'none';
  resultsWrap.style.display = 'block';
  reportTabs.style.display = 'flex';
}

// ─── Render Results ──────────────────────────────
function renderResults(data, code) {
  const r = data.result;
  showResults();

  // Default to overview tab
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector('.tab[data-tab="overview"]')?.classList.add('active');
  $('tab-overview')?.classList.add('active');

  renderOverview(r);
  renderErrors(r.errors || []);
  renderFixedCode(r.corrected_code || '');
  renderTips(r.optimizations || []);
  highlightErrorLines(r.errors || []);

  const errCount = (r.errors||[]).filter(e=>e.severity==='error').length;
  showToast(`✅ Analysis complete — ${errCount} error(s) found`);
}

// ─── Overview ────────────────────────────────────
function renderOverview(r) {
  const score = r.overall_score ?? 75;
  animateScore(score);
  $('scoreSummary').textContent = r.summary || '';

  // Badges
  const errors   = (r.errors||[]).filter(e=>e.severity==='error').length;
  const warnings = (r.errors||[]).filter(e=>e.severity==='warning').length;
  const infos    = (r.errors||[]).filter(e=>e.severity==='info').length;
  const badges   = $('scoreBadges');
  badges.innerHTML = '';
  if (errors)   badges.innerHTML += `<span class="badge badge-error">🔴 ${errors} Error${errors>1?'s':''}</span>`;
  if (warnings) badges.innerHTML += `<span class="badge badge-warning">🟡 ${warnings} Warning${warnings>1?'s':''}</span>`;
  if (infos)    badges.innerHTML += `<span class="badge badge-info">🔵 ${infos} Info</span>`;
  if (!errors && !warnings) badges.innerHTML += `<span class="badge badge-success">✅ Clean Code</span>`;

  // Error summary boxes
  $('errorSummary').innerHTML = `
    <div class="err-count-box type-error">
      <span class="err-count-num">${errors}</span>
      <span class="err-count-label">Errors</span>
    </div>
    <div class="err-count-box type-warning">
      <span class="err-count-num">${warnings}</span>
      <span class="err-count-label">Warnings</span>
    </div>
    <div class="err-count-box type-info">
      <span class="err-count-num">${infos}</span>
      <span class="err-count-label">Info</span>
    </div>`;

  // Concepts
  const conceptsSection = $('conceptsSection');
  const conceptsList    = $('conceptsList');
  if (r.concepts_explained && r.concepts_explained.length) {
    conceptsSection.style.display = 'block';
    conceptsList.innerHTML = r.concepts_explained.map(c => `
      <div class="concept-card">
        <div class="concept-name">📖 ${esc(c.concept)}</div>
        <div class="concept-desc">${esc(c.explanation)}</div>
      </div>`).join('');
  } else {
    conceptsSection.style.display = 'none';
  }

  // Complexity
  const complexitySection = $('complexitySection');
  if (r.complexity && (r.complexity.time !== 'N/A' || r.complexity.space !== 'N/A')) {
    complexitySection.style.display = 'block';
    $('complexityCards').innerHTML = `
      <div class="complexity-card">
        <div class="complexity-label">Time Complexity</div>
        <div class="complexity-value">${esc(r.complexity.time||'N/A')}</div>
      </div>
      <div class="complexity-card">
        <div class="complexity-label">Space Complexity</div>
        <div class="complexity-value">${esc(r.complexity.space||'N/A')}</div>
      </div>`;
  } else {
    complexitySection.style.display = 'none';
  }
}

function animateScore(target) {
  const ring = $('scoreRingFill');
  const numEl = $('scoreNum');
  const circumference = 314;
  const offset = circumference - (target / 100) * circumference;
  let color = target >= 80 ? '#22d3a5' : target >= 50 ? '#ffb547' : '#ff5a7a';
  ring.style.stroke = color;

  setTimeout(() => { ring.style.strokeDashoffset = offset; }, 100);

  let current = 0;
  const step = target / 60;
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    numEl.textContent = Math.round(current);
    if (current >= target) clearInterval(timer);
  }, 20);
}

// ─── Errors Tab ──────────────────────────────────
function renderErrors(errors) {
  const list = $('errorsList');
  if (!errors.length) {
    list.innerHTML = `<div class="no-errors-msg">
      <span class="no-err-icon">🎉</span>
      <strong>No issues found!</strong><br>
      <span style="font-size:0.82rem;color:var(--text2)">Your code looks clean.</span>
    </div>`;
    return;
  }

  const icons = { error: '🔴', warning: '🟡', info: '🔵', success: '🟢' };
  list.innerHTML = errors.map((e, i) => `
    <div class="error-card sev-${e.severity||'info'}" style="animation-delay:${i*0.06}s">
      <div class="error-card-header">
        <span class="error-icon">${icons[e.severity]||'🔵'}</span>
        <span class="error-title">${esc(e.message||'Unknown issue')}</span>
        ${e.line ? `<span class="error-line">Line ${e.line}</span>` : ''}
        <span class="error-type-tag">${esc(e.type||e.severity||'issue')}</span>
      </div>
      <div class="error-desc">${esc(e.description||'')}</div>
      ${e.fix ? `<div class="error-fix">${esc(e.fix)}</div>` : ''}
    </div>`).join('');
}

// ─── Fixed Code Tab ──────────────────────────────
function renderFixedCode(fixedCode) {
  const wrap   = $('fixedCodeWrap');
  const noFix  = $('noFixMsg');
  if (!fixedCode || fixedCode.trim() === '') {
    wrap.style.display = 'none';
    noFix.style.display = 'block';
    return;
  }
  wrap.style.display = 'block';
  noFix.style.display = 'none';

  // Normalize indentation: ensure consistent 4-space indent
  const normalized = fixedCode.replace(/\t/g, '    ');

  const ta = document.getElementById('fixedCodeEditor');
  if (!fixedEditor) {
    fixedEditor = CodeMirror.fromTextArea(ta, {
      theme: 'dracula',
      lineNumbers: true,
      readOnly: true,
      mode: LANG_MODES[currentLanguage] || 'python',
      lineWrapping: false,
      tabSize: 4,
      indentUnit: 4,
      indentWithTabs: false
    });
  }
  fixedEditor.setOption('mode', LANG_MODES[currentLanguage] || 'python');
  fixedEditor.setOption('tabSize', 4);
  fixedEditor.setOption('indentUnit', 4);
  fixedEditor.setValue(normalized);
  setTimeout(() => fixedEditor.refresh(), 50);
}

// ─── Tips Tab ────────────────────────────────────
function renderTips(tips) {
  const list = $('tipsList');
  if (!tips.length) {
    list.innerHTML = `<p style="color:var(--text2);font-size:0.82rem;">No specific tips. Your code is already well-structured!</p>`;
    return;
  }
  list.innerHTML = tips.map((tip, i) => `
    <div class="tip-card" style="animation-delay:${i*0.08}s">
      <div class="tip-num">${i+1}</div>
      <div class="tip-text">${esc(tip)}</div>
    </div>`).join('');
}

// ─── Line Highlighting ───────────────────────────
function highlightErrorLines(errors) {
  clearHighlights();
  errors.forEach(e => {
    if (!e.line) return;
    const lineNo = e.line - 1;
    const cls = e.severity === 'error' ? 'cm-error-line' : 'cm-warn-line';
    const mark = editor.addLineClass(lineNo, 'background', cls);
    errorLineMarks.push({ mark, lineNo, cls });
  });
}

function clearHighlights() {
  errorLineMarks.forEach(({ lineNo, cls }) => {
    editor.removeLineClass(lineNo, 'background', cls);
  });
  errorLineMarks = [];
}

// ─── Toast ───────────────────────────────────────
let toastTimer;
function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3000);
}

// ─── Escape HTML ─────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
