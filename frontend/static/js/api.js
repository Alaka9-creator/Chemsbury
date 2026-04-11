/**
 * api.js — fetch wrapper with auth headers and unified error handling.
 * Depends on auth.js being loaded first.
 */

const API = (() => {
  function _headers(extra = {}) {
    return {
      'Authorization': 'Bearer ' + Auth.getToken(),
      ...extra,
    };
  }

  async function _handle(resp) {
    if (resp.status === 401) { Auth.logout(); return null; }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
  }

  async function get(endpoint) {
    const resp = await fetch(endpoint, { headers: _headers() });
    return _handle(resp);
  }

  async function post(endpoint, body) {
    const resp = await fetch(endpoint, {
      method:  'POST',
      headers: _headers({ 'Content-Type': 'application/json' }),
      body:    JSON.stringify(body),
    });
    return _handle(resp);
  }

  async function put(endpoint, body) {
    const resp = await fetch(endpoint, {
      method:  'PUT',
      headers: _headers({ 'Content-Type': 'application/json' }),
      body:    JSON.stringify(body),
    });
    return _handle(resp);
  }

  async function del(endpoint) {
    const resp = await fetch(endpoint, {
      method:  'DELETE',
      headers: _headers(),
    });
    return _handle(resp);
  }

  return { get, post, put, delete: del };
})();
