/**
 * Runtime configuration. Values come from Vite environment variables so they
 * can differ per build without touching component code:
 *
 *   - development: defaults below (backend on 127.0.0.1:8000), or override in
 *     `desktop/.env.development.local`
 *   - production:  put `VITE_API_BASE_URL` in `desktop/.env.production` before
 *     `npm run tauri build`
 *
 * Use the .env files, not a shell variable: this Vite version does not read
 * `VITE_*` from the process environment. See `desktop/.env.example`.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

/** Abort backend requests that take longer than this. LLM replies can take a
 *  while, so this is generous; the backend has its own 30 s provider timeout. */
export const API_TIMEOUT_MS = 45000;
