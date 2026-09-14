/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL, e.g. "http://127.0.0.1:8000". Optional; see src/config.ts. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
