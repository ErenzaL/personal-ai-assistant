import { useCallback, useEffect, useRef, useState } from "react";
import { connectGmail, describeApiError, disconnectGmail, getGmailStatus } from "../services/api";

export interface GmailState {
  connected: boolean;
  /** A short, safe-to-show reason, only when there's something worth saying
   *  beyond plain connected/not (currently just a refresh that failed to
   *  reach Google -- the connection may still be fine). */
  detail: string | null;
  /** The connected account's own address, when known. Never set unless
   *  `connected` is true. */
  email: string | null;
}

/**
 * Gmail's connection status, read live from the backend (which itself reads
 * live from the token file and Google, never a cached flag) and the two
 * actions Settings offers: connect and disconnect. No message content and
 * no token ever passes through this hook -- there is nothing here to.
 */
export function useGmail(enabled: boolean) {
  const [status, setStatus] = useState<GmailState | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    try {
      const next = await getGmailStatus();
      if (mounted.current) {
        setStatus(next);
        setError(null);
      }
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    }
  }, []);

  useEffect(() => {
    if (enabled) void reload();
  }, [enabled, reload]);

  const connect = useCallback(async () => {
    setIsBusy(true);
    setError(null);
    try {
      const next = await connectGmail();
      if (mounted.current) setStatus(next);
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    } finally {
      if (mounted.current) setIsBusy(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    setIsBusy(true);
    try {
      const next = await disconnectGmail();
      if (mounted.current) {
        setStatus(next);
        setError(null);
      }
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    } finally {
      if (mounted.current) setIsBusy(false);
    }
  }, []);

  return { status, isBusy, error, connect, disconnect };
}
