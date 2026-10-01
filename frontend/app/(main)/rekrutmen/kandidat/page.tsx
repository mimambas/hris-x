"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type { Candidate, JobApplication } from "@/lib/types";
import {
  PageHeader,
  Spinner,
  ErrorBox,
  EmptyState,
  Modal,
  Field,
  inputCls,
  btnPrimary,
  btnSecondary,
} from "@/components/ui";

const STAGE_LABEL: Record<string, string> = {
  applied: "Dilamar",
  screening: "Seleksi",
  interview: "Wawancara",
  offering: "Penawaran",
  hired: "Diterima",
  rejected: "Ditolak",
  withdrawn: "Mundur",
};

const SOURCES = ["website", "referral", "job_portal"];

interface CandRow extends Candidate {
  latestStage: string | null;
  appCount: number;
}

export default function KandidatPage() {
  const [rows, setRows] = useState<CandRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [fName, setFName] = useState("");
  const [fEmail, setFEmail] = useState("");
  const [fPhone, setFPhone] = useState("");
  const [fSource, setFSource] = useState("website");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [cands, apps] = await Promise.all([
        apiFetch<Candidate[]>("/recruitment/candidates"),
        apiFetch<JobApplication[]>("/recruitment/applications"),
      ]);
      const byCand = new Map<string, JobApplication[]>();
      for (const a of apps) {
        const list = byCand.get(a.candidate_id) ?? [];
        list.push(a);
        byCand.set(a.candidate_id, list);
      }
      setRows(
        cands.map((c) => {
          const la = (byCand.get(c.id) ?? []).sort((x, y) =>
            y.applied_at.localeCompare(x.applied_at)
          );
          return {
            ...c,
            latestStage: la[0]?.status ?? null,
            appCount: la.length,
          };
        })
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat daftar kandidat.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (stageFilter && r.latestStage !== stageFilter) return false;
      if (!q) return true;
      return (
        r.name.toLowerCase().includes(q) || r.email.toLowerCase().includes(q)
      );
    });
  }, [rows, query, stageFilter]);

  async function createCandidate() {
    if (!fName.trim() || !fEmail.trim()) {
      setActionError("Nama dan email wajib diisi.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const created = await apiFetch<Candidate>("/recruitment/candidates", {
        method: "POST",
        body: JSON.stringify({
          name: fName.trim(),
          email: fEmail.trim().toLowerCase(),
          phone: fPhone.trim() || null,
          source: fSource,
        }),
      });
      setRows((list) => [{ ...created, latestStage: null, appCount: 0 }, ...list]);
      setShowForm(false);
      setFName("");
      setFEmail("");
      setFPhone("");
      setFSource("website");
      setSuccessMsg(`Kandidat "${created.name}" ditambahkan.`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menambah kandidat.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Kandidat"
        subtitle={`${filtered.length} dari ${rows.length} kandidat`}
        action={
          <button className={btnPrimary} onClick={() => setShowForm(true)}>
            ＋ Tambah kandidat
          </button>
        }
      />

      {successMsg && (
        <div className="mb-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200">
          {successMsg}
        </div>
      )}
      {actionError && !showForm && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
          {actionError}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Cari nama atau email…"
          className={`${inputCls} max-w-xs`}
        />
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
          className={inputCls}
        >
          <option value="">Semua tahap</option>
          {Object.entries(STAGE_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState message="Tidak ada kandidat yang cocok dengan filter." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="px-4 py-3 font-medium">Nama</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Telepon</th>
                <th className="px-4 py-3 font-medium">Sumber</th>
                <th className="px-4 py-3 font-medium">Lamaran</th>
                <th className="px-4 py-3 font-medium">Tahap terakhir</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3">
                    <Link
                      href={`/rekrutmen/kandidat/${r.id}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {r.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{r.email}</td>
                  <td className="px-4 py-3 text-slate-600">{r.phone ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{r.source}</td>
                  <td className="px-4 py-3 text-slate-600">{r.appCount}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {r.latestStage ? (STAGE_LABEL[r.latestStage] ?? r.latestStage) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <Modal
          title="Tambah kandidat"
          onClose={() => setShowForm(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowForm(false)}>
                Batal
              </button>
              <button className={btnPrimary} disabled={busy} onClick={createCandidate}>
                {busy ? "Menyimpan…" : "Simpan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            {actionError && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
                {actionError}
              </div>
            )}
            <Field label="Nama lengkap" required>
              <input
                value={fName}
                onChange={(e) => setFName(e.target.value)}
                className={inputCls}
                maxLength={200}
              />
            </Field>
            <Field label="Email" required>
              <input
                type="email"
                value={fEmail}
                onChange={(e) => setFEmail(e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Telepon">
              <input
                value={fPhone}
                onChange={(e) => setFPhone(e.target.value)}
                className={inputCls}
                maxLength={30}
              />
            </Field>
            <Field label="Sumber">
              <select value={fSource} onChange={(e) => setFSource(e.target.value)} className={inputCls}>
                {SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Modal>
      )}
    </div>
  );
}
