/**
 * auth.js — shared authentication utilities
 * Include on every protected page.
 */

const Auth = (() => {
  const TOKEN_KEY = 'chem_token';
  const USER_KEY  = 'chem_user';

  function getToken()  { return localStorage.getItem(TOKEN_KEY); }
  function getUser()   {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || '{}'); }
    catch { return {}; }
  }

  function saveSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function logout() {
    clearSession();
    window.location.href = '/';
  }

  /** Verify token with server; redirect to / if invalid. */
  async function requireAuth() {
    const token = getToken();
    if (!token) { window.location.href = '/'; return null; }
    try {
      const resp = await fetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (!resp.ok) { clearSession(); window.location.href = '/'; return null; }
      const user = await resp.json();
      saveSession(token, user);   // refresh cached user data
      return user;
    } catch {
      window.location.href = '/';
      return null;
    }
  }

  /** Redirect if already logged in (use on login/register pages). */
  async function redirectIfLoggedIn(dest = '/app') {
    const token = getToken();
    if (!token) return;
    try {
      const resp = await fetch('/api/me', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (resp.ok) window.location.href = dest;
    } catch { /* ignore */ }
  }

  /**
   * Populate header: avatar initial, user name, admin link visibility.
   * Expects elements: #navAvatar, #navUserName, #adminLink (optional).
   */
  function initNav(user) {
    const avatar = document.getElementById('navAvatar');
    const nameEl = document.getElementById('navUserName');
    const adminL = document.getElementById('adminLink');
    if (avatar) avatar.textContent = (user.name || '?').charAt(0).toUpperCase();
    if (nameEl) nameEl.textContent = (user.name || '').split(' ')[0];
    if (adminL) adminL.style.display = user.role === 'admin' ? '' : 'none';
  }

  return { getToken, getUser, saveSession, clearSession, logout, requireAuth, redirectIfLoggedIn, initNav };
})();

// Expose logout globally so inline onclick="Auth.logout()" works
window.authLogout = () => Auth.logout();
