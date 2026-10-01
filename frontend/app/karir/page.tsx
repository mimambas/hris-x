"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getApiBase } from "@/lib/api";
import type { PublicJob } from "@/lib/types";
import { tanggal } from "@/lib/format";

export default function KarirPage() {
  const [slug, setSlug] = useState("hashiru");
  const [jobs, setJobs] = useState<PublicJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  async function load(s: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${getApiBase()}/public/jobs?tenant=${encodeURIComponent(s)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setJobs(await res.json());
    } catch {
      setError("Gagal memuat daftar lowongan. Pastikan nama tenant benar.");
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("hashiru");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = jobs.filter((j) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      j.title.toLowerCase().includes(q) ||
      (j.location ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Karir</h1>
            <p className="text-sm text-slate-500">
              Temukan lowongan kerja terbaru di perusahaan kami.
            </p>
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              load(slug.trim() || "hashiru");
            }}
          >
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="Nama tenant"
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              aria-label="Nama tenant"
            />
            <button
              type="submit"
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              Cari
            </button>
          </form>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 py-8">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Cari posisi atau lokasi…"
          className="mb-6 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm"
        />

        {loading && <p className="text-sm text-slate-500">Memuat lowongan…</p>}
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
            {error}
          </div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="rounded-xl bg-white p-10 text-center text-sm text-slate-500 ring-1 ring-slate-200">
            Tidak ada lowongan yang tersedia saat ini. Silakan kembali lagi nanti.
          </div>
        )}

        <div className="grid gap-4">
          {filtered.map((j) => (
            <Link
              key={j.id}
              href={`/karir/${j.id}`}
              className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md"
            >
              <h2 className="text-lg font-semibold text-brand-700">{j.title}</h2>
              <p className="mt-1 text-sm text-slate-500">
                {[j.employment_type, j.location].filter(Boolean).join(" · ")}
                {j.published_at && ` · Tayang ${tanggal(j.published_at)}`}
              </p>
              <p className="mt-2 line-clamp-2 text-sm text-slate-600">
                {j.description || "—"}
              </p>
              <span className="mt-3 inline-block text-sm font-medium text-brand-700">
                Lihat detail & lamar →
              </span>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
