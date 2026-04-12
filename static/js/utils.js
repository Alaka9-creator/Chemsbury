/**
 * utils.js — shared helper functions used across all pages.
 */

/* ── XSS-safe HTML escape ── */
function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

/* ── Date formatting ── */
function shortDate(dt) {
  if (!dt) return '—';
  const d = new Date(dt.endsWith('Z') ? dt : dt + 'Z');
  return d.toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' });
}

function longDate(dt) {
  if (!dt) return '—';
  const d = new Date(dt.endsWith('Z') ? dt : dt + 'Z');
  return shortDate(dt) + ' ' + d.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit' });
}

/* ── Status badge HTML ── */
function statusBadge(s) {
  const map = {
    safe:    ['✅', 'Safe',    'safe'],
    caution: ['🔔', 'Caution', 'caution'],
    unsafe:  ['⚠️', 'Unsafe',  'unsafe'],
  };
  const [icon, label, cls] = map[s] || ['—', 'Unknown', 'caution'];
  return `<span class="status-badge ${escHtml(cls)}">${icon} ${escHtml(label)}</span>`;
}

/* ── Confidence badge ── */
function confidenceBadge(c) {
  const colors = { high:'var(--success)', medium:'var(--warning)', low:'var(--danger)' };
  const col = colors[c] || 'var(--text3)';
  return `<span style="font-size:0.78rem;color:${col};font-weight:600;text-transform:capitalize;">${escHtml(c || '—')}</span>`;
}

/* ── Toast notification ── */
function showToast(msg, duration = 3000) {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.style.display = 'none'; }, duration);
}

/* ── Show / hide spinner on a button ── */
function setLoading(btnEl, textEl, spinnerEl, loading, loadingText, defaultText) {
  btnEl.disabled        = loading;
  textEl.textContent    = loading ? loadingText : defaultText;
  spinnerEl.style.display = loading ? 'block' : 'none';
}
