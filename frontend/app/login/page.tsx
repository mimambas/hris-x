"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthContext";
import { Field, inputCls, btnPrimary } from "@/components/ui";

export default function LoginPage() {
  const { login, token, ready } = useAuth();
  const router = useRouter();
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (ready && token) {
    router.replace("/dashboard");
    return null;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(tenantSlug.trim(), email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal masuk.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
        <div className="mb-6 text-center">
          <p className="text-2xl font-bold tracking-tight text-slate-900">HRIS-X</p>
          <p className="mt-1 text-sm text-slate-500">Masuk ke akun Anda</p>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          <Field label="Slug tenant" required>
            <input
              className={inputCls}
              value={tenantSlug}
              onChange={(e) => setTenantSlug(e.target.value)}
              placeholder="mis. hashiru"
              autoComplete="organization"
              required
            />
          </Field>
          <Field label="Email" required>
            <input
              className={inputCls}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="nama@perusahaan.id"
              autoComplete="email"
              required
            />
          </Field>
          <Field label="Kata sandi" required>
            <input
              className={inputCls}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          <button type="submit" disabled={busy} className={`${btnPrimary} w-full py-2.5`}>
            {busy ? "Memproses…" : "Masuk"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-400">
          Hubungi administrator bila Anda lupa kredensial.
        </p>
      </div>
    </div>
  );
}
