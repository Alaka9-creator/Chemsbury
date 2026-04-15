/**
 * api.js — improved version (safe, consistent, production-ready)
 */

const API = (() => {

  function _headers(extra = {}) {
    return {
      'Authorization': 'Bearer ' + Auth.getToken(),
      'Content-Type': 'application/json',
      ...extra,
    };
  }

  async function _handle(resp) {
    const data = await resp.json().catch(() => ({}));

    // 🔒 Handle unauthorized properly
    if (resp.status === 401) {
      Auth.logout();
      throw new Error("Session expired. Please login again.");
    }

    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }

    return data;
  }

  // 🔥 Add timeout support (important)
  async function _fetchWithTimeout(url, options, timeout = 10000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);

    try {
      const resp = await fetch(url, {
        ...options,
        signal: controller.signal
      });
      return resp;
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error("Request timed out");
      }
      throw err;
    } finally {
      clearTimeout(id);
    }
  }

  async function get(endpoint) {
    const resp = await _fetchWithTimeout(endpoint, {
      method: 'GET',
      headers: _headers(),
    });
    return _handle(resp);
  }

  async function post(endpoint, body) {
    const resp = await _fetchWithTimeout(endpoint, {
      method: 'POST',
      headers: _headers(),
      body: JSON.stringify(body),
    });
    return _handle(resp);
  }

  async function put(endpoint, body) {
    const resp = await _fetchWithTimeout(endpoint, {
      method: 'PUT',
      headers: _headers(),
      body: JSON.stringify(body),
    });
    return _handle(resp);
  }

  async function del(endpoint) {
    const resp = await _fetchWithTimeout(endpoint, {
      method: 'DELETE',
      headers: _headers(),
    });
    return _handle(resp);
  }

  return { get, post, put, delete: del };
})();