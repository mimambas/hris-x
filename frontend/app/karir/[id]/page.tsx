"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getApiBase, apiFetch, ApiError } from "@/lib/api";
import { getToken } from "@/components/AuthContext";
import type { PublicJob, Candidate, JobApplication, Me } from "@/lib/types";
import { tanggal } from "@/lib/format";
import { Field, inputCls, btnPrimary } from "@/components/ui";

export default function KarirDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [job, setJob] = useState<PublicJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [loggedIn, setLoggedIn] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [slug, setSlug] = useState("hashiru");

  // Form lamaran
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  useEffect(() => {
    // Token disimpan di localStorage (AuthContext), bukan cookie.
    const token = getToken();
    setLoggedIn(!!token);
    if (token) {
      apiFetch<Me>("/me")
        .then((m) => {
          setMe(m);
          setName(m.full_name);
          setEmail(m.email);
        })
        .catch(() => setLoggedIn(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          `${getApiBase()}/public/jobs?tenant=${encodeURIComponent(slug)}`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const list: PublicJob[] = await res.json();
        const found = list.find((j) => j.id === id) ?? null;
        if (!found) setError("Lowongan tidak ditemukan atau sudah ditutup.");
        setJob(found);
      } catch {
        setError("Gagal memuat detail lowongan.");
      } finally {
        setLoading(false);
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function apply() {
    if (!name.trim() || !email.trim()) {
      setFormError("Nama dan email wajib diisi.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    setFormSuccess(null);
    try {
      // 1. Cari kandidat by email, atau buat baru
      const cands = await apiFetch<Candidate[]>("/recruitment/candidates");
      const lower = email.trim().toLowerCase();
      let cand = cands.find((c) => c.email.toLowerCase() === lower);
      if (!cand) {
        cand = await apiFetch<Candidate>("/recruitment/candidates", {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            email: lower,
            phone: phone.trim() || null,
            source: "website",
          }),
        });
      }
      // 2. Buat lamaran
      await apiFetch<JobApplication>("/recruitment/applications", {
        method: "POST",
        body: JSON.stringify({ posting_id: id, candidate_id: cand.id }),
      });
      setFormSuccess(
        "Lamaran terkirim. Tim rekrutmen akan menghubungi Anda bila lolos seleksi awal."
      );
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message.includes("sudah")
            ? "Anda sudah pernah melamar lowongan ini."
            : err.message
          : "Gagal mengirim lamaran."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-5">
          <Link href="/karir" className="text-sm font-medium text-brand-700 hover:underline">
            ← Semua lowongan
          </Link>
          <div className="flex items-center gap-2">
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-36 rounded-lg border border-slate-300 px-2 py-1 text-xs"
              aria-label="Nama tenant"
            />
            <button
              onClick={() => window.location.reload()}
              className="text-xs text-slate-500 hover:underline"
            >
              Muat ulang
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 py-8">
        {loading && <p className="text-sm text-slate-500">Memuat…</p>}
        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
            {error}
          </div>
        )}
        {job && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200 lg:col-span-2">
              <h1 className="text-2xl font-bold text-slate-900">{job.title}</h1>
              <p className="mt-1 text-sm text-slate-500">
                {[job.employment_type, job.location].filter(Boolean).join(" · ")}
                {job.published_at && ` · Tayang ${tanggal(job.published_at)}`}
              </p>
              <h2 className="mb-2 mt-6 text-sm font-semibold text-slate-700">Deskripsi</h2>
              <p className="whitespace-pre-wrap text-sm text-slate-800">
                {job.description || "—"}
              </p>
              <h2 className="mb-2 mt-6 text-sm font-semibold text-slate-700">Persyaratan</h2>
              <p className="whitespace-pre-wrap text-sm text-slate-800">
                {job.requirements || "—"}
              </p>
            </div>

            <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-4 text-lg font-semibold">Lamar posisi ini</h2>
              {!loggedIn ? (
                <div className="space-y-3">
                  <p className="text-sm text-slate-600">
                    Lamaran online saat ini tersedia untuk pengguna yang sudah masuk.
                    Anda bisa masuk dulu, atau mengirim CV langsung ke tim rekrutmen
                    perusahaan.
                  </p>
                  <Link
                    href="/login"
                    className="inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
                  >
                    Masuk untuk melamar
                  </Link>
                </div>
              ) : (
                <div className="space-y-3">
                  {formError && (
                    <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
                      {formError}
                    </div>
                  )}
                  {formSuccess ? (
                    <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200">
                      {formSuccess}
                    </div>
                  ) : (
                    <>
                      <Field label="Nama lengkap" required>
                        <input
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <Field label="Email" required>
                        <input
                          type="email"
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <Field label="Telepon">
                        <input
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <button
                        className={btnPrimary}
                        disabled={submitting}
                        onClick={apply}
                      >
                        {submitting ? "Mengirim…" : "Kirim lamaran"}
                      </button>
                      <p className="text-xs text-slate-400">
                        Masuk sebagai {me?.full_name ?? me?.email ?? "pengguna terdaftar"}.
                      </p>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
