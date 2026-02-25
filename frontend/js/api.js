/**
 * Centralized API utilities shared across all non-module pages.
 * Loaded as a plain <script> before page-specific scripts.
 */

/**
 * Fetch wrapper with automatic JSON parsing and error extraction.
 * @param {string} path  - API path (e.g. '/api/v1/k8s/templates/all')
 * @param {RequestInit} options - fetch options merged after {credentials:'include'}
 * @returns {Promise<any>} - parsed JSON response
 * @throws {Error} with message from response body (detail/message) or HTTP status
 */
window.api = async function api(path, options = {}) {
  const resp = await fetch(path, { credentials: 'include', ...options });
  let payload = null;
  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) payload = await resp.json();
  if (!resp.ok) {
    const msg = (payload && (payload.detail || payload.message)) || `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return payload;
};

/**
 * Returns whether SSO is enabled on the server.
 * @returns {Promise<boolean>}
 */
window.checkSsoStatus = async function checkSsoStatus() {
  try {
    const resp = await fetch('/api/v1/auth/sso/status');
    if (!resp.ok) return false;
    const data = await resp.json();
    return !!data.sso_enabled;
  } catch {
    return false;
  }
};
