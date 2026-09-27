// Ortak yardımcılar: API çağrısı (X-API-Key), explain[] render, rozet, anahtar çubuğu
const AG_KEY = 'ag_api_key';
function getKey() { try { return sessionStorage.getItem(AG_KEY) || ''; } catch (e) { return ''; } }
function setKey(v) { try { v ? sessionStorage.setItem(AG_KEY, v) : sessionStorage.removeItem(AG_KEY); } catch (e) { } }

async function api(path, body, method) {
  const headers = { 'content-type': 'application/json' };
  const key = getKey();
  if (key) headers['x-api-key'] = key;
  const r = await fetch(path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) showKeyBar();
  if (!r.ok) {
    const d = j.detail;
    const msg = typeof d === 'string' ? d : (d && d.message) || (Array.isArray(d) ? d.map(x => x.msg).join('; ') : r.statusText);
    throw Object.assign(new Error(msg), { status: r.status, body: j });
  }
  return j;
}

// API_KEYS tanımlıysa anahtar sorulur; sekme kapanınca unutulur (sessionStorage)
function showKeyBar() {
  if (document.getElementById('keybar')) return;
  const bar = document.createElement('div');
  bar.id = 'keybar';
  bar.className = 'keybar';
  bar.innerHTML = `<span>Bu sunucu API anahtarı istiyor.</span><input id="keyInput" type="password" autocomplete="off" placeholder="X-API-Key">
    <button id="keySave">Kaydet</button>`;
  document.body.prepend(bar);
  document.getElementById('keySave').onclick = () => { setKey(document.getElementById('keyInput').value.trim()); location.reload(); };
}

function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function renderExplain(list) {
  if (!list || !list.length) return '';
  return `<div class="explain"><h4>Neden bu karar? — explain[]</h4><ul>` + list.map(e =>
    `<li class="${e.triggered ? 'trig' : ''}"><span class="sig">${esc(e.signal)}</span><span>${esc(typeof e.value === 'object' ? JSON.stringify(e.value) : e.value)} — ${esc(e.note)}</span><span class="w">w=${esc(e.weight)}${e.source ? ' · ' + esc(e.source) : ''}</span></li>`
  ).join('') + `</ul></div>`;
}
function badge(level, text) { return `<span class="badge ${esc(level)}">${esc(text)}</span>`; }
const BAD_DECISIONS = ['impostor', 'withhold_pickup', 'alarm', 'trouble', 'driver_rejected', 'no_monitoring'];
const OK_DECISIONS = ['genuine', 'release_pickup', 'close_case', 'ok', 'lower', 'driver_verified', 'start_monitoring'];
const WARN_DECISIONS = ['raise', 'probable_traffic', 'transit', 'unexpected', 'unverified', 'overdue', 'await_operator_consent'];
function decisionLevel(d) { return BAD_DECISIONS.includes(d) ? 'bad' : OK_DECISIONS.includes(d) ? 'ok' : WARN_DECISIONS.includes(d) ? 'warn' : ''; }
function hm(iso) { try { return new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } }
async function loadHealth(elId) {
  try {
    const h = await api('/health'); const el = document.getElementById(elId);
    if (el && h.nac) el.textContent = `NaC modu: ${h.nac.mode}${h.nac.base_url ? ' · ' + h.nac.base_url : ''} · depo: ${h.store} · bildirim: ${h.notify}`;
  } catch (e) { }
}
