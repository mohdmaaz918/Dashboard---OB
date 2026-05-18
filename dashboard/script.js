/* ── state ── */
const API = '';
// const API = 'https://dashboard-ob.onrender.com';
let singleData = null;
let bulkRows = [];
let bulkFilter = 'all';
let bulkSearch = '';
let bulkDisplayed = [];
let gaugeChart = null;
let catChartObj = null;
let currentAppId = null;
let currentModalFilename = null;

/* ── view management ── */
function showView(name, el) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.ni').forEach(n => n.classList.remove('active'));
  const v = document.getElementById('view-' + name);
  if (v) v.classList.add('active');
  if (el) el.classList.add('active');
  const labels = {upload:'New Assessment',single:'Single Result',bulk:'Bulk Review',pricing:'Pricing Schedule'};
  document.getElementById('breadcrumb').innerHTML = `<span>${labels[name] || name}</span>`;
  if (name === 'pricing') loadPricing();
}

/* ── API health ── */
async function checkApi() {
  try {
    const r = await fetch(API + '/health', {signal: AbortSignal.timeout(3000)});
    if (r.ok) { setApiStatus(true); } else throw 0;
  } catch { setApiStatus(false); }
}
function setApiStatus(ok) {
  const dot = document.getElementById('api-dot');
  const lbl = document.getElementById('api-lbl');
  dot.style.background = ok ? '#10b981' : '#ef4444';
  lbl.textContent = ok ? 'Online' : 'Offline';
  lbl.style.color = ok ? '#10b981' : '#ef4444';
}

/* ── drag & drop ── */
function initDrop(zoneId, handler) {
  const z = document.getElementById(zoneId);
  z.addEventListener('dragover', e => { e.preventDefault(); z.classList.add('drag-over'); });
  z.addEventListener('dragleave', () => z.classList.remove('drag-over'));
  z.addEventListener('drop', e => {
    e.preventDefault(); z.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) handler(f);
  });
}

/* ── helpers ── */
function params() {
  return {
    amount: parseFloat(document.getElementById('p-amount').value) || 500,
    term: parseInt(document.getElementById('p-term').value) || 4,
    lookback: parseInt(document.getElementById('p-lookback').value) || 3,
    cadence: document.getElementById('p-cadence').value || 'monthly',
  };
}

function fmt(v, p='$') {
  if (v == null) return '—';
  return p + Math.abs(parseFloat(v)).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}
function fmtSigned(v) {
  if (v == null) return '—';
  const n = parseFloat(v);
  const sign = n < 0 ? '-$' : '$';
  return sign + Math.abs(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
}
function pct(v) { if (v == null) return '—'; return parseFloat(v).toFixed(1) + '%'; }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function normDec(d) {
  if (!d) return 'DECLINE';
  if (d === 'APPROVE' || d === 'ACCEPT') return 'APPROVE';
  if (d === 'REFER') return 'REFER';
  return 'DECLINE';
}
function decColor(d) {
  const n = normDec(d);
  if (n === 'APPROVE') return '#10b981';
  if (n === 'REFER')   return '#f59e0b';
  return '#ef4444';
}
function siColor(v, mx) {
  if (v == null) return '#64748b';
  const r = v/mx;
  return r >= .6 ? '#10b981' : r >= .3 ? '#f59e0b' : '#ef4444';
}
function riskColor(lv) {
  if (!lv) return '#64748b';
  const l = lv.toLowerCase();
  if (l.includes('very high') || l.includes('high')) return '#ef4444';
  if (l.includes('med') || l.includes('mod')) return '#f59e0b';
  return '#10b981';
}

/* ── loading / toast ── */
function showLoad(txt, sub='') {
  document.getElementById('load-txt').textContent = txt;
  document.getElementById('load-sub').textContent = sub;
  document.getElementById('loading').classList.add('open');
}
function hideLoad() { document.getElementById('loading').classList.remove('open'); }
function toast(msg, type='') {
  const tc = document.getElementById('toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  tc.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

/* ══════════════════════════════
   SINGLE FILE
══════════════════════════════ */
function handleSingle(file) {
  if (!file) return;
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['json','xml'].includes(ext)) { toast('Please upload a JSON or XML file','err'); return; }
  scoreSingle(file);
}

async function scoreSingle(file) {
  showLoad(`Scoring ${file.name}…`, 'Running pipeline: categorisation + scoring');
  const p = params();
  const fd = new FormData();
  fd.append('file', file);
  fd.append('requested_amount', p.amount);
  fd.append('requested_term', p.term);
  fd.append('lookback_months', p.lookback);
  fd.append('pricing_cadence', p.cadence);

  try {
    const r = await fetch(API + '/v1/score-file', {method:'POST', body:fd});
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Scoring failed');

    singleData = {...data, filename: file.name, ts: new Date().toLocaleString()};
    currentAppId = file.name + '_' + Date.now();

    // Switch view first so the user always sees the results page
    document.getElementById('nav-single').style.display = '';
    showView('single', document.getElementById('nav-single'));

    renderSingle(singleData);
    toast(`Decision: ${data.result.decision}`, data.result.decision === 'APPROVE' ? 'ok' : '');
  } catch(e) {
    console.error('scoreSingle error:', e);
    toast('Error: ' + e.message, 'err');
  } finally { hideLoad(); }
}

/* ══════════════════════════════
   BULK FILE
══════════════════════════════ */
function handleBulk(file) {
  if (!file) return;
  if (!file.name.endsWith('.zip')) { toast('Please upload a ZIP file','err'); return; }
  processBulk(file);
}

async function processBulk(file) {
  showLoad(`Processing ${file.name}…`, 'This may take a moment for large batches');
  const p = params();
  const fd = new FormData();
  fd.append('file', file);
  fd.append('requested_amount', p.amount);
  fd.append('requested_term', p.term);
  fd.append('lookback_months', p.lookback);
  fd.append('pricing_cadence', p.cadence);

  try {
    const r = await fetch(API + '/v1/bulk-score-zip', {method:'POST', body:fd});
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Bulk processing failed');

    bulkRows = data.results || [];
    document.getElementById('bulk-lbl').textContent = `${file.name} · ${data.files_processed} files processed`;
    document.getElementById('nav-bulk').style.display = '';
    showView('bulk', document.getElementById('nav-bulk'));
    renderBulk();
    toast(`Processed ${data.files_processed} applications`);
  } catch(e) {
    console.error('processBulk error:', e);
    toast('Error: ' + e.message, 'err');
  } finally { hideLoad(); }
}

/* ══════════════════════════════
   RENDER SINGLE
══════════════════════════════ */
function renderSingle(data) {
  const r = data.result;
  const m = r.metrics;
  const dec = normDec(r.decision);

  // header
  document.getElementById('s-filename').textContent = data.filename;
  document.getElementById('s-meta').textContent = `Scored · ${data.ts} · ${r.lookback_months}m lookback`;
  const badge = document.getElementById('s-badge');
  badge.textContent = dec; badge.className = 'db ' + dec;

  // gauge
  const score = r.score || 0;
  document.getElementById('g-num').textContent = score;
  document.getElementById('g-num').style.color = decColor(dec);
  const dl = document.getElementById('g-dec');
  dl.textContent = dec; dl.className = 'dec-lbl ' + dec;
  document.getElementById('g-risk').textContent = r.risk_level || '';
  document.getElementById('g-amounts').innerHTML =
    `Max approved: <strong>${fmt(r.max_approved_amount)}</strong> · ${r.max_approved_term||0} months`;

  renderGauge(score, dec);

  // flags
  const reasons = [...(r.referral_reasons||[]), ...(r.decline_reasons||[])];
  const fg = document.getElementById('g-flags');
  if (reasons.length) {
    fg.innerHTML = `<h5>Flags</h5>` + reasons.map(x=>`<div class="flag-pill">⚠ ${esc(x)}</div>`).join('');
  } else {
    fg.innerHTML = `<div class="ok-flag">✓ No adverse flags</div>`;
  }

  // score breakdown
  const sb = r.score_breakdown || {};
  document.getElementById('g-breakdown').innerHTML = [
    ['Affordability', sb.affordability_score, 30],
    ['Income Quality', sb.income_quality_score, 25],
    ['Acct Conduct', sb.account_conduct_score, 25],
    ['Risk Indicators', sb.risk_indicators_score, 20],
  ].map(([l,v,mx]) => `<div class="sb-cell">
    <div class="sl">${l}</div>
    <div class="sv" style="color:${siColor(v,mx)}">${v??'—'}<span class="sm"> /${mx}</span></div>
  </div>`).join('');

  // metric cards
  const aff = m.affordability || {};
  const inc = m.income       || {};
  const exp = m.expense      || {};
  const dbt = m.debt         || {};
  const bal = m.balance      || {};
  document.getElementById('m-inc').textContent = fmt(inc.monthly_income);
  document.getElementById('m-inc-s').innerHTML = `Stable: ${fmt(inc.monthly_stable_income)}<br>Sources: ${(inc.income_sources||[]).join(', ')||'None'}`;
  const expBreak = exp.essential_breakdown || {};
  document.getElementById('m-exp').textContent = fmt(exp.monthly_essential_total);
  document.getElementById('m-exp-s').innerHTML =
    `Sum of all outgoings excl. discretionary<br>` +
    `Unpaid ${fmt(expBreak.unpaid||0)} · Other ${fmt(expBreak.other_expenses||0)} · ` +
    `Discret. ${fmt(expBreak.discretionary||0)} (separate)`;
  document.getElementById('m-dbt').textContent = fmt(dbt.monthly_debt_payments);
  document.getElementById('m-dbt-s').innerHTML = `CC: ${fmt(dbt.monthly_credit_card_payments)}<br>Loans: ${fmt(dbt.monthly_other_loan_payments)}`;
  const disp = aff.monthly_disposable || 0;
  const dispEl = document.getElementById('m-disp');
  dispEl.textContent = fmtSigned(disp);
  dispEl.style.color = disp < 0 ? 'var(--bad)' : 'var(--ok)';
  const dispCard = document.getElementById('mc-disp');
  dispCard.style.borderLeftColor = disp < 0 ? 'var(--bad)' : 'var(--ok)';
  dispCard.style.background = disp < 0 ? '#fff8f8' : '#f0fdf9';
  document.getElementById('m-disp-s').innerHTML =
    `Post-loan: <strong style="color:${aff.post_loan_disposable<0?'var(--bad)':'var(--ok)'}">${fmtSigned(aff.post_loan_disposable)}</strong><br>` +
    `Avg balance: ${fmt(bal.average_balance)} (OD: ${bal.days_in_overdraft}d)`;

  // detail cards
  document.getElementById('d-afford').innerHTML = [
    ['Disposable /mo',    fmtSigned(aff.monthly_disposable),           aff.monthly_disposable<0?'neg':'pos'],
    ['DTI Ratio',         pct(aff.debt_to_income_ratio),               aff.debt_to_income_ratio>40?'neg':'pos'],
    ['Essential Ratio',   pct(aff.essential_ratio),                    aff.essential_ratio>100?'wrn':''],
    ['Post-loan Disp.',   fmtSigned(aff.post_loan_disposable),         aff.post_loan_disposable<0?'neg':'pos'],
    ['Repayment /mo',     fmt(aff.proposed_repayment),                 ''],
    ['Repay/Disposable',  pct(aff.repayment_to_disposable_ratio),      aff.repayment_to_disposable_ratio>30?'wrn':'pos'],
  ].map(([k,v,c]) => `<div class="dr"><span class="k">${k}</span><span class="v ${c}">${v}</span></div>`).join('');

  document.getElementById('d-income').innerHTML = [
    ['Total (period)',  fmt(inc.total_income)],
    ['Monthly',        fmt(inc.monthly_income)],
    ['Stable',         fmt(inc.monthly_stable_income)],
    ['Gig Economy',    fmt(inc.monthly_gig_income)],
    ['Stability',      (inc.income_stability_score||0).toFixed(1)+'/100'],
    ['Regularity',     (inc.income_regularity_score||0).toFixed(1)+'/100'],
  ].map(([k,v]) => `<div class="dr"><span class="k">${k}</span><span class="v">${v}</span></div>`).join('');

  const risk = m.risk || {};
  document.getElementById('d-risk').innerHTML = [
    ['Gambling Total',      fmt(risk.gambling_total),             risk.gambling_total>0],
    ['Failed Pmts (45d)',   risk.failed_payments_count_45d,       risk.failed_payments_count_45d>0],
    ['Bank Charges (90d)',  risk.bank_charges_count_90d,          risk.bank_charges_count_90d>3],
    ['New Credit (90d)',    risk.new_credit_providers_90d,        risk.new_credit_providers_90d>3],
    ['Debt Collection',     risk.debt_collection_activity,        risk.debt_collection_activity>0],
    ['Savings Activity',    fmt(risk.savings_activity||0),        false],
  ].map(([k,v,bad]) => `<div class="dr"><span class="k">${k}</span><span class="v ${bad?'neg':'pos'}">${v}</span></div>`).join('');

  // category chart
  if (data.categorization?.summary) renderCatChart(data.categorization.summary);

  // transactions
  const txns = data.categorization?.results || [];
  document.getElementById('txn-count').textContent = `(${txns.length} transactions)`;
  document.getElementById('txn-body').innerHTML = txns.slice(0,30).map(t => {
    const amt = parseFloat(t.amount||0);
    return `<tr>
      <td style="color:var(--muted);white-space:nowrap">${t.date}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.description)}">${esc(t.description)}</td>
      <td style="font-weight:600;white-space:nowrap;color:${amt<0?'var(--ok)':'var(--bad)'}">
        ${amt<0?'+':''}${fmt(amt)}
      </td>
      <td><span class="cc cc-${t.category}">${t.category}/${t.subcategory}</span></td>
      <td style="color:var(--muted)">${((t.confidence||0)*100).toFixed(0)}%</td>
    </tr>`;
  }).join('');

  // reset UW panel
  document.getElementById('uw-comment').value = '';
  document.getElementById('uw-ok').classList.remove('show');
  document.querySelectorAll('.uw-btns .btn').forEach(b => { b.style.display=''; b.disabled=false; });
}

/* ── gauge chart ── */
function renderGauge(score, dec) {
  const ctx = document.getElementById('gauge').getContext('2d');
  if (gaugeChart) gaugeChart.destroy();
  gaugeChart = new Chart(ctx, {
    type:'doughnut',
    data:{ datasets:[{ data:[score,100-score], backgroundColor:[decColor(dec),'#f1f5f9'], borderWidth:0 }] },
    options:{ rotation:-90, circumference:180, cutout:'72%',
      plugins:{legend:{display:false},tooltip:{enabled:false}},
      animation:{duration:600}
    }
  });
}

/* ── category donut ── */
const CAT_COLORS = {income:'#10b981',expense:'#f97316',transfer:'#3b82f6',debt:'#ef4444',essential:'#8b5cf6'};

function renderCatChart(summary) {
  const ctx = document.getElementById('cat-chart').getContext('2d');
  if (catChartObj) catChartObj.destroy();
  const byC = summary.by_category || {};
  const labels = Object.keys(byC);
  const vals = Object.values(byC);
  const colors = labels.map(l => CAT_COLORS[l] || '#94a3b8');

  catChartObj = new Chart(ctx, {
    type:'doughnut',
    data:{ labels, datasets:[{ data:vals, backgroundColor:colors, borderWidth:2, borderColor:'#fff', hoverOffset:4 }] },
    options:{ cutout:'60%',
      plugins:{ legend:{display:false},
        tooltip:{ callbacks:{ label: c => ` ${c.label}: ${c.parsed} txns` } }
      },
      animation:{duration:500}
    }
  });

  document.getElementById('cat-legend').innerHTML = labels.map((l,i) =>
    `<div class="li"><div class="ld" style="background:${colors[i]}"></div><span>${l} (${vals[i]})</span></div>`
  ).join('');
}

/* ══════════════════════════════
   UNDERWRITER (single)
══════════════════════════════ */
async function submitDecision(dec) {
  const comment = document.getElementById('uw-comment').value.trim();
  try {
    await fetch(API + '/v1/decision', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        app_id: currentAppId,
        filename: singleData?.filename,
        uw_decision: dec,
        comment,
        submitted_at: new Date().toISOString(),
        system_decision: singleData?.result?.decision,
        score: singleData?.result?.score,
      })
    });
  } catch {}

  const ok = document.getElementById('uw-ok');
  ok.classList.add('show');
  document.getElementById('uw-ok-txt').textContent = `Decision recorded: ${dec}${comment ? ' · "'+comment.substring(0,50)+(comment.length>50?'…':'"') : ''}`;
  document.getElementById('uw-ok-time').textContent = new Date().toLocaleString();
  document.querySelectorAll('.uw-btns .btn').forEach(b => b.style.display='none');
  toast(`${dec} submitted`, dec==='APPROVE'?'ok':'');
}

/* ══════════════════════════════
   BULK RENDER
══════════════════════════════ */
function renderBulk() {
  const counts = {APPROVE:0,REFER:0,DECLINE:0};
  bulkRows.forEach(r => {
    const d = r.success && r.result ? normDec(r.result.decision) : 'DECLINE';
    counts[d]++;
  });
  document.getElementById('bc-all').textContent     = bulkRows.length;
  document.getElementById('bc-approve').textContent = counts.APPROVE;
  document.getElementById('bc-refer').textContent   = counts.REFER;
  document.getElementById('bc-decline').textContent = counts.DECLINE;
  renderBulkTable();
}

function filterBulk(f, el) {
  bulkFilter = f;
  document.querySelectorAll('.sc').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  renderBulkTable();
}

function searchBulk(q) { bulkSearch = q.toLowerCase(); renderBulkTable(); }

function renderBulkTable() {
  bulkDisplayed = bulkRows.filter(r => {
    if (bulkSearch && !r.filename.toLowerCase().includes(bulkSearch)) return false;
    if (bulkFilter === 'all') return true;
    const d = r.success && r.result ? normDec(r.result.decision) : 'DECLINE';
    return d === bulkFilter;
  });

  document.getElementById('bulk-body').innerHTML = bulkDisplayed.map((r, i) => {
    if (!r.success) return `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td style="font-weight:500">${esc(r.filename)}</td>
      <td colspan="7" style="color:var(--bad);font-size:12px">Error: ${esc(r.error||'Unknown error')}</td>
      <td>—</td></tr>`;

    const res = r.result; const m = res.metrics||{};
    const dec = normDec(res.decision);
    const score = res.score||0;
    const pc = score>=60?'hi':score>=40?'mid':'lo';
    const dti = m.affordability?.debt_to_income_ratio||0;
    const fp  = m.risk?.failed_payments_count_45d||0;
    const inc = m.income?.monthly_income||0;
    const exp = m.expense?.monthly_essential_total||0;

    return `<tr>
      <td style="color:var(--muted)">${i+1}</td>
      <td style="font-weight:500;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.filename)}">${esc(r.filename)}</td>
      <td><span class="db ${dec}">${dec}</span></td>
      <td>
        <div class="flex aic gap8">
          <div class="sp ${pc}">${score}</div>
          <div class="pb-wrap"><div class="pb-fill" style="width:${score}%;background:${decColor(dec)}"></div></div>
        </div>
      </td>
      <td>${fmt(inc)}</td>
      <td>${fmt(exp)}</td>
      <td style="font-weight:600;color:${dti>40?'var(--bad)':'var(--ok)'}">${dti.toFixed(1)}%</td>
      <td style="font-weight:600;color:${fp>0?'var(--bad)':'var(--ok)'}">${fp}</td>
      <td style="font-size:12px;font-weight:500;color:${riskColor(res.risk_level)}">${res.risk_level||'—'}</td>
      <td><button class="btn btn-out btn-sm" onclick="openModal(${i})">Review</button></td>
    </tr>`;
  }).join('');
}

/* ══════════════════════════════
   BULK REVIEW MODAL
══════════════════════════════ */
function openModal(idx) {
  const r = bulkDisplayed[idx];
  if (!r || !r.success) return;
  currentModalFilename = r.filename;

  const res = r.result; const m = res.metrics||{};
  const dec = normDec(res.decision);
  const score = res.score||0;
  const reasons = [...(res.referral_reasons||[]), ...(res.decline_reasons||[])];
  const aff = m.affordability||{}; const inc = m.income||{};
  const exp = m.expense||{}; const dbt = m.debt||{};
  const risk = m.risk||{};
  const sb = res.score_breakdown||{};

  const decBg   = dec==='APPROVE'?'#ecfdf5':dec==='REFER'?'#fffbeb':'#fef2f2';
  const decBord = dec==='APPROVE'?'#6ee7b7':dec==='REFER'?'#fcd34d':'#fca5a5';

  document.getElementById('modal-title').textContent = r.filename;
  document.getElementById('modal-body').innerHTML = `
    <!-- Banner -->
    <div style="background:${decBg};border:1px solid ${decBord};border-radius:12px;padding:16px 20px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
      <div class="flex aic gap10">
        <div style="font-size:38px;font-weight:800;color:${decColor(dec)}">${score}</div>
        <div>
          <div style="font-size:20px;font-weight:800;color:${decColor(dec)}">${dec}</div>
          <div style="font-size:12px;color:var(--muted)">${res.risk_level||''} · Max: ${fmt(res.max_approved_amount)} for ${res.max_approved_term||0} months</div>
        </div>
      </div>
      <div>${reasons.length
        ? reasons.slice(0,3).map(x=>`<div style="font-size:12px;color:var(--bad);font-weight:500">⚠ ${esc(x)}</div>`).join('')
        : `<div style="color:var(--ok);font-size:13px;font-weight:500">✓ No adverse flags</div>`
      }</div>
    </div>

    <!-- 4 metric mini-cards -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px">
      ${[
        ['Income /mo',      fmt(inc.monthly_income),             `Stable: ${fmt(inc.monthly_stable_income)}`,                         '#10b981'],
        ['Expenses /mo',    fmt(exp.monthly_essential_total||0), `Unpaid: ${fmt((exp.essential_breakdown||{}).unpaid||0)} + other items`,'#f59e0b'],
        ['Debt /mo',        fmt(dbt.monthly_debt_payments||0),   `DTI: ${pct(aff.debt_to_income_ratio)}`,                             '#ef4444'],
        ['Net Disposable',  fmtSigned(aff.monthly_disposable||0),`Post-loan: ${fmtSigned(aff.post_loan_disposable||0)}`,              aff.monthly_disposable<0?'#ef4444':'#10b981'],
      ].map(([l,v,sub,c]) => `<div style="background:#fff;border-radius:9px;padding:12px 14px;border-left:3px solid ${c};box-shadow:var(--sh1)">
        <div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:3px">${l}</div>
        <div style="font-size:18px;font-weight:700;margin-bottom:2px;color:${c}">${v}</div>
        <div style="font-size:11px;color:var(--muted)">${sub}</div>
      </div>`).join('')}
    </div>

    <!-- 3 detail cols -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px">
      <div style="background:#fff;border-radius:9px;padding:12px 14px;box-shadow:var(--sh1)">
        <div style="font-size:10px;font-weight:600;text-transform:uppercase;color:var(--muted);margin-bottom:8px">💳 Affordability</div>
        ${[
          ['Disposable',     fmtSigned(aff.monthly_disposable),     aff.monthly_disposable<0],
          ['DTI',            pct(aff.debt_to_income_ratio),         aff.debt_to_income_ratio>40],
          ['Post-loan disp.',fmtSigned(aff.post_loan_disposable),   aff.post_loan_disposable<0],
          ['Repayment /mo',  fmt(aff.proposed_repayment),           false],
        ].map(([k,v,bad])=>`<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px;border-bottom:1px solid #f8fafc">
          <span style="color:var(--muted)">${k}</span>
          <span style="font-weight:600;color:${bad?'var(--bad)':'var(--ok)'}">${v}</span>
        </div>`).join('')}
      </div>
      <div style="background:#fff;border-radius:9px;padding:12px 14px;box-shadow:var(--sh1)">
        <div style="font-size:10px;font-weight:600;text-transform:uppercase;color:var(--muted);margin-bottom:8px">📊 Score Breakdown</div>
        ${[
          ['Affordability',sb.affordability_score,30],
          ['Income quality',sb.income_quality_score,25],
          ['Acct conduct',sb.account_conduct_score,25],
          ['Risk indicators',sb.risk_indicators_score,20],
        ].map(([k,v,mx])=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:12px;border-bottom:1px solid #f8fafc">
          <span style="color:var(--muted)">${k}</span>
          <span style="font-weight:700;color:${siColor(v,mx)}">${v??'—'}<span style="font-weight:400;font-size:10px;color:var(--muted)">/${mx}</span></span>
        </div>`).join('')}
      </div>
      <div style="background:#fff;border-radius:9px;padding:12px 14px;box-shadow:var(--sh1)">
        <div style="font-size:10px;font-weight:600;text-transform:uppercase;color:var(--muted);margin-bottom:8px">⚠️ Risk</div>
        ${[
          ['Gambling',         fmt(risk.gambling_total||0),       risk.gambling_total>0],
          ['Failed pmts (45d)',risk.failed_payments_count_45d||0, risk.failed_payments_count_45d>0],
          ['Bank chgs (90d)',  risk.bank_charges_count_90d||0,    risk.bank_charges_count_90d>3],
          ['New credit (90d)', risk.new_credit_providers_90d||0,  risk.new_credit_providers_90d>3],
        ].map(([k,v,bad])=>`<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:12px;border-bottom:1px solid #f8fafc">
          <span style="color:var(--muted)">${k}</span>
          <span style="font-weight:600;color:${bad?'var(--bad)':'var(--ok)'}">${v}</span>
        </div>`).join('')}
      </div>
    </div>

    <!-- Underwriter -->
    <div style="background:#fff;border-radius:12px;padding:16px 18px;border-top:3px solid var(--border);box-shadow:var(--sh1)">
      <div style="font-size:13.5px;font-weight:700;margin-bottom:10px">✍️ Underwriter Decision</div>
      <div style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:flex-end">
        <div>
          <label style="font-size:11.5px;font-weight:500;color:var(--muted);display:block;margin-bottom:3px">Comments / Notes</label>
          <textarea id="modal-comment" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:6px;font-family:inherit;font-size:13px;resize:none;height:60px;outline:none" placeholder="Add notes…"></textarea>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px">
          <button class="btn btn-ok btn-sm" onclick="submitModalDecision('APPROVE')">✓ Approve</button>
          <button class="btn btn-warn btn-sm" onclick="submitModalDecision('REFER')">⚡ Refer</button>
          <button class="btn btn-bad btn-sm" onclick="submitModalDecision('DECLINE')">✗ Decline</button>
        </div>
      </div>
      <div id="modal-uw-ok" style="display:none;margin-top:10px;padding:9px 13px;background:var(--ok-bg);border:1px solid var(--ok-br);border-radius:8px;font-size:13px;font-weight:600;color:#065f46"></div>
    </div>
  `;

  document.getElementById('modal').classList.add('open');
}

async function submitModalDecision(dec) {
  const comment = document.getElementById('modal-comment').value.trim();
  try {
    await fetch(API + '/v1/decision', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        app_id: currentModalFilename + '_modal',
        filename: currentModalFilename,
        uw_decision: dec,
        comment,
        submitted_at: new Date().toISOString(),
      })
    });
  } catch {}

  const el = document.getElementById('modal-uw-ok');
  el.style.display = 'block';
  el.textContent = `✅ Decision recorded: ${dec} · ${new Date().toLocaleTimeString()}`;
  document.querySelectorAll('#modal-body .btn').forEach(b => b.disabled = true);
  toast(`${currentModalFilename}: ${dec}`, dec==='APPROVE'?'ok':'');
}

function closeModal() { document.getElementById('modal').classList.remove('open'); }

/* ══════════════════════════════
   PRICING
══════════════════════════════ */
async function loadPricing() {
  try {
    const r = await fetch(API + '/v1/pricing');
    const d = await r.json();
    const sched = d.schedule || {};
    let rows = '';
    for (const [cadence, tiers] of Object.entries(sched)) {
      for (const [anchor, rate] of Object.entries(tiers)) {
        const dailyPct = (parseFloat(rate)*100).toFixed(4);
        const simplePa = (parseFloat(rate)*365*100).toFixed(2);
        rows += `<tr style="border-top:1px solid #f1f5f9">
          <td style="padding:8px 12px;font-weight:600">£${anchor}</td>
          <td style="padding:8px 12px">${cadence}</td>
          <td style="padding:8px 12px">${dailyPct}%</td>
          <td style="padding:8px 12px;font-weight:600">${simplePa}%</td>
        </tr>`;
      }
    }
    document.getElementById('pricing-body').innerHTML = `
      <div style="margin-bottom:18px">
        <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px">Loan Range</div>
        <div style="font-size:22px;font-weight:700">£${d.min_loan_amount} – £${d.max_loan_amount}</div>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead style="background:#f8fafc">
          <tr>
            <th style="text-align:left;padding:8px 12px;font-size:10.5px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.4px">Amount</th>
            <th style="text-align:left;padding:8px 12px;font-size:10.5px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.4px">Cadence</th>
            <th style="text-align:left;padding:8px 12px;font-size:10.5px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.4px">Daily Rate</th>
            <th style="text-align:left;padding:8px 12px;font-size:10.5px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.4px">Simple PA</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  } catch {
    document.getElementById('pricing-body').innerHTML =
      '<p style="color:var(--bad);font-size:13px">Failed to load. Is the API server running?</p>';
  }
}

/* ══════════════════════════════
   DOWNLOADS
══════════════════════════════ */
function triggerDownload(content, filename, mime) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], {type: mime}));
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ── PDF (html2canvas → jsPDF) ── */
async function downloadPDF(mode) {
  const btnId = mode === 'single' ? 'btn-single-pdf' : 'btn-bulk-pdf';
  const btn = document.getElementById(btnId);
  const origTxt = btn.textContent;
  btn.textContent = 'Generating…';
  btn.disabled = true;

  const view = document.querySelector('.view.active');
  const main = document.querySelector('.main');

  // temporarily unclip so html2canvas sees full height
  const saved = { mO: main.style.overflow, mH: main.style.maxHeight, bO: document.body.style.overflow, bH: document.body.style.height };
  main.style.overflow   = 'visible';
  main.style.maxHeight  = 'none';
  document.body.style.overflow = 'visible';
  document.body.style.height   = 'auto';

  try {
    const canvas = await html2canvas(view, {
      scale: 1.8,
      useCORS: true,
      backgroundColor: '#f1f5f9',
      scrollX: 0,
      scrollY: -window.scrollY,
      width:  view.scrollWidth,
      height: view.scrollHeight,
      windowWidth:  view.scrollWidth,
      windowHeight: view.scrollHeight,
    });

    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const imgW  = pageW;
    const imgH  = (canvas.height * imgW) / canvas.width;
    const img   = canvas.toDataURL('image/jpeg', 0.92);

    // stamp header on every page
    const label = mode === 'single'
      ? `Chirp Underwriting Report — ${singleData?.filename || ''} — ${new Date().toLocaleString()}`
      : `Chirp Bulk Report — ${document.getElementById('bulk-lbl').textContent} — ${new Date().toLocaleString()}`;

    let yOffset = 0;
    let page = 0;
    while (yOffset < imgH) {
      if (page > 0) pdf.addPage();
      pdf.setFontSize(7);
      pdf.setTextColor(150);
      pdf.text(label, 5, 4);
      const contentY = 6;
      const contentH = pageH - contentY;
      pdf.addImage(img, 'JPEG', 0, contentY - yOffset, imgW, imgH);
      // clip overflowing content on this page
      pdf.setFillColor(255, 255, 255);
      pdf.rect(0, contentY + contentH, pageW, pageH, 'F'); // white mask below
      yOffset += contentH;
      page++;
    }

    const fname = (mode === 'single' ? (singleData?.filename || 'report') : 'chirp_bulk')
      .replace(/\.[^.]+$/, '') + '_report.pdf';
    pdf.save(fname);
    toast('Downloaded ' + fname, 'ok');
  } catch(e) {
    toast('PDF failed: ' + e.message, 'err');
  } finally {
    main.style.overflow  = saved.mO;
    main.style.maxHeight = saved.mH;
    document.body.style.overflow = saved.bO;
    document.body.style.height   = saved.bH;
    btn.textContent = origTxt;
    btn.disabled = false;
  }
}

/* ── Single-view CSV ── */
function downloadSingleCSV() {
  if (!singleData) return;
  const r = singleData.result;
  const m = r.metrics || {};
  const aff = m.affordability || {}; const inc = m.income || {};
  const exp = m.expense || {}; const eb = exp.essential_breakdown || {};
  const dbt = m.debt || {}; const bal = m.balance || {};
  const risk = m.risk || {}; const sb = r.score_breakdown || {};
  const reasons = [...(r.referral_reasons||[]), ...(r.decline_reasons||[])].join('; ');

  const lines = [
    ['CHIRP UNDERWRITING REPORT'],
    ['Exported At', new Date().toLocaleString()],
    ['Filename', singleData.filename],
    [],
    ['DECISION'],
    ['Decision', normDec(r.decision)],
    ['Score', r.score],
    ['Risk Level', r.risk_level || ''],
    ['Max Approved Amount', r.max_approved_amount],
    ['Max Approved Term (months)', r.max_approved_term],
    ['Flags', reasons],
    [],
    ['SCORE BREAKDOWN'],
    ['Affordability Score', `${sb.affordability_score ?? ''} / 30`],
    ['Income Quality Score', `${sb.income_quality_score ?? ''} / 25`],
    ['Account Conduct Score', `${sb.account_conduct_score ?? ''} / 25`],
    ['Risk Indicators Score', `${sb.risk_indicators_score ?? ''} / 20`],
    [],
    ['INCOME'],
    ['Monthly Income', inc.monthly_income],
    ['Monthly Stable Income', inc.monthly_stable_income],
    ['Monthly Gig Income', inc.monthly_gig_income],
    ['Total Income (period)', inc.total_income],
    ['Income Sources', (inc.income_sources||[]).join('; ')],
    ['Income Stability Score', inc.income_stability_score],
    ['Income Regularity Score', inc.income_regularity_score],
    [],
    ['EXPENSES (monthly)'],
    ['Essential Total', exp.monthly_essential_total],
    ['Housing', exp.monthly_housing],
    ['Utilities', exp.monthly_utilities],
    ['Groceries', exp.monthly_groceries],
    ['Transport', exp.monthly_transport],
    ['Food & Dining', eb.food_dining],
    ['Unpaid', eb.unpaid],
    ['Other Expenses', eb.other_expenses],
    ['Discretionary', eb.discretionary],
    ['Gambling', eb.gambling],
    [],
    ['DEBT (monthly)'],
    ['Total Debt Payments', dbt.monthly_debt_payments],
    ['Credit Cards', dbt.monthly_credit_card_payments],
    ['Other Loans', dbt.monthly_other_loan_payments],
    ['HCSTC Payments', dbt.monthly_hcstc_payments],
    ['BNPL Payments', dbt.monthly_bnpl_payments],
    [],
    ['AFFORDABILITY'],
    ['Net Disposable Income', aff.monthly_disposable],
    ['Post-loan Disposable', aff.post_loan_disposable],
    ['DTI Ratio (%)', aff.debt_to_income_ratio],
    ['Essential Ratio (%)', aff.essential_ratio],
    ['Proposed Repayment', aff.proposed_repayment],
    ['Repayment to Disposable (%)', aff.repayment_to_disposable_ratio],
    ['Is Affordable', aff.is_affordable],
    [],
    ['BALANCE'],
    ['Average Balance', bal.average_balance],
    ['Minimum Balance', bal.minimum_balance],
    ['Maximum Balance', bal.maximum_balance],
    ['Days in Overdraft', bal.days_in_overdraft],
    [],
    ['RISK INDICATORS'],
    ['Gambling Total', risk.gambling_total],
    ['Failed Payments (total)', risk.failed_payments_count],
    ['Failed Payments (45d)', risk.failed_payments_count_45d],
    ['Bank Charges (total)', risk.bank_charges_count],
    ['Bank Charges (90d)', risk.bank_charges_count_90d],
    ['New Credit Providers (90d)', risk.new_credit_providers_90d],
    ['Debt Collection Activity', risk.debt_collection_activity],
    ['Savings Activity', risk.savings_activity],
    [],
    ['TRANSACTIONS'],
    ['Date','Description','Amount','Category','Subcategory','Confidence','Match Method','Risk Level'],
  ];

  const txns = singleData.categorization?.results || [];
  txns.forEach(t => lines.push([
    t.date, t.description, t.amount, t.category, t.subcategory,
    (t.confidence*100).toFixed(0) + '%', t.match_method, t.risk_level || '',
  ]));

  const csv = lines.map(row =>
    row.length === 0 ? '' :
    row.map(v => v == null ? '' : `"${String(v).replace(/"/g,'""')}"`).join(',')
  ).join('\n');

  const base = singleData.filename.replace(/\.[^.]+$/, '');
  triggerDownload(csv, `${base}_report.csv`, 'text/csv');
  toast('Downloaded ' + base + '_report.csv', 'ok');
}

function downloadBulkJSON() {
  if (!bulkRows.length) return;
  const out = {
    exported_at: new Date().toISOString(),
    total: bulkRows.length,
    results: bulkRows,
  };
  triggerDownload(JSON.stringify(out, null, 2), 'chirp_bulk_results.json', 'application/json');
  toast('Downloaded chirp_bulk_results.json');
}

function downloadBulkCSV() {
  if (!bulkRows.length) return;
  const headers = [
    'Filename','Decision','Score','Risk Level',
    'Monthly Income','Monthly Expenses','Monthly Debt','Net Disposable',
    'DTI %','Post-loan Disposable','Proposed Repayment',
    'Avg Balance','Overdraft Days',
    'Failed Payments 45d','Bank Charges 90d','New Credit 90d','Gambling Total',
    'Income Sources','Income Stability','Income Regularity',
    'Affordability Score','Income Quality Score','Account Conduct Score','Risk Indicators Score',
    'Max Approved Amount','Max Approved Term','Referral Reasons','Error',
  ];
  const csvRows = [headers.join(',')];
  for (const r of bulkRows) {
    if (!r.success) {
      const row = new Array(headers.length).fill('');
      row[0] = `"${r.filename}"`;
      row[1] = 'ERROR';
      row[headers.length - 1] = `"${(r.error||'').replace(/"/g,'""')}"`;
      csvRows.push(row.join(','));
      continue;
    }
    const res = r.result; const m = res.metrics||{};
    const aff = m.affordability||{}; const inc = m.income||{};
    const exp = m.expense||{}; const dbt = m.debt||{};
    const bal = m.balance||{}; const risk = m.risk||{};
    const sb = res.score_breakdown||{};
    const reasons = [...(res.referral_reasons||[]), ...(res.decline_reasons||[])].join('; ');
    const row = [
      `"${r.filename}"`,
      normDec(res.decision),
      res.score||0,
      `"${res.risk_level||''}"`,
      (inc.monthly_income||0).toFixed(2),
      (exp.monthly_essential_total||0).toFixed(2),
      (dbt.monthly_debt_payments||0).toFixed(2),
      (aff.monthly_disposable||0).toFixed(2),
      (aff.debt_to_income_ratio||0).toFixed(1),
      (aff.post_loan_disposable||0).toFixed(2),
      (aff.proposed_repayment||0).toFixed(2),
      (bal.average_balance||0).toFixed(2),
      bal.days_in_overdraft||0,
      risk.failed_payments_count_45d||0,
      risk.bank_charges_count_90d||0,
      risk.new_credit_providers_90d||0,
      (risk.gambling_total||0).toFixed(2),
      `"${(inc.income_sources||[]).join('; ')}"`,
      (inc.income_stability_score||0).toFixed(1),
      (inc.income_regularity_score||0).toFixed(1),
      sb.affordability_score||0,
      sb.income_quality_score||0,
      sb.account_conduct_score||0,
      sb.risk_indicators_score||0,
      res.max_approved_amount||0,
      res.max_approved_term||0,
      `"${reasons.replace(/"/g,'""')}"`,
      '',
    ];
    csvRows.push(row.join(','));
  }
  triggerDownload(csvRows.join('\n'), 'chirp_bulk_results.csv', 'text/csv');
  toast('Downloaded chirp_bulk_results.csv');
}

/* ══════════════════════════════
   INIT
══════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  checkApi();
  initDrop('single-zone', handleSingle);
  initDrop('bulk-zone', handleBulk);

  document.getElementById('modal').addEventListener('click', e => {
    if (e.target.id === 'modal') closeModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  setInterval(checkApi, 30000);
});
