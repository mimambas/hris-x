"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import type { LoginResponse, Me } from "@/lib/types";

const TOKEN_KEY = "hrisx_token";
const USER_KEY = "hrisx_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface AuthCtx {
  token: string | null;
  user: Me | null;
  ready: boolean;
  login: (tenantSlug: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({
  token: null,
  user: null,
  ready: false,
  login: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const t = getToken();
    setToken(t);
    try {
      const raw = window.localStorage.getItem(USER_KEY);
      setUser(raw ? (JSON.parse(raw) as Me) : null);
    } catch {
      setUser(null);
    }
    setReady(true);
  }, []);

  const login = useCallback(
    async (tenantSlug: string, email: string, password: string) => {
      let res: Response;
      try {
        res = await fetch(`${BASE}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenant_slug: tenantSlug,
            email,
            password,
          }),
        });
      } catch {
        throw new Error("Tidak dapat terhubung ke server. Periksa koneksi Anda.");
      }
      if (!res.ok) {
        let msg = "Gagal masuk. Periksa kembali data Anda.";
        try {
          const body = await res.json();
          if (typeof body?.detail === "string" && body.detail.trim())
            msg = body.detail;
        } catch {
          /* abaikan */
        }
        if (res.status === 429)
          msg = "Terlalu banyak percobaan masuk. Tunggu sebentar lalu coba lagi.";
        throw new Error(msg);
      }
      const data = (await res.json()) as LoginResponse;
      window.localStorage.setItem(TOKEN_KEY, data.access_token);

      // Ambil profil untuk nama & peran.
      const meRes = await fetch(`${BASE}/me`, {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      let me: Me | null = null;
      if (meRes.ok) {
        me = (await meRes.json()) as Me;
        window.localStorage.setItem(USER_KEY, JSON.stringify(me));
      }
      setToken(data.access_token);
      setUser(me);
      router.replace("/dashboard");
    },
    [router]
  );

  const logout = useCallback(() => {
    clearAuth();
    setToken(null);
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({ token, user, ready, login, logout }),
    [token, user, ready, login, logout]
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  return useContext(Ctx);
}
