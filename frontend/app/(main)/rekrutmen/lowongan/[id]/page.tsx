"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  JobPosting,
  JobApplication,
  Candidate,
  Me,
  Interview,
} from "@/lib/types";
import { tanggal, tanggalWaktu } from "@/lib/format";
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
  btnSmall,
} from "@/components/ui";

const STAGES = [
  "applied",
  "screening",
  "interview",
  "offering",
  "hired",
  "rejected",
  "withdrawn",
] as const;

const STAGE_LABEL: Record<string, string> = {
  applied: "Dilamar",
  screening: "Seleksi",
  interview: "Wawancara",
  offering: "Penawaran",
  hired: "Diterima",
  rejected: "Ditolak",
  withdrawn: "Mundur",
};

const POSTING_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  published: "Tayang",
  closed: "Ditutup",
};

interface AppRow extends JobApplication {
  candidateName: string;
  candidateEmail: string;
}

export default function PostingDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [posting, setPosting] = useState<JobPosting | null>(null);
  const [apps, setApps] = useState<AppRow[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Modal pindah tahap
  const [moving, setMoving] = useState<AppRow | null>(null);
  const [toStage, setToStage] = useState("screening");
  const [moveNote, setMoveNote] = useState("");

  // Modal jadwal interview
  const [scheduling, setScheduling] = useState<AppRow | null>(null);
  const [ivAt, setIvAt] = useState("");
  const [ivMode, setIvMode] = useState("onsite");
  const [ivLoc, setIvLoc] = useState("");
  const [ivExtra, setIvExtra] = useState("");

  // Modal tambah pelamar manual
  const [adding, setAdding] = useState(false);
  const [addCandId, setAddCandId] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [p, a, cands, m] = await Promise.all([
        apiFetch<JobPosting>(`/recruitment/postings/${id}`),
        apiFetch<JobApplication[]>(`/recruitment/applications?posting_id=${id}`),
        apiFetch<Candidate[]>("/recruitment/candidates"),
        apiFetch<Me>("/me"),
      ]);
      const candMap = new Map(cands.map((c) => [c.id, c]));
      setPosting(p);
      setCandidates(cands);
      setApps(
        a.map((x) => ({
          ...x,
          candidateName: candMap.get(x.candidate_id)?.name ?? "—",
          candidateEmail: candMap.get(x.candidate_id)?.email ?? "—",
        }))
      );
      setMe(m);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat detail lowongan.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const grouped = useMemo(() => {
    const g: Record<string, AppRow[]> = {};
    for (const s of STAGES) g[s] = [];
    for (const a of apps) {
      if (g[a.status]) g[a.status].push(a);
      else g.applied.push(a);
    }
    return g;
  }, [apps]);

  async function moveApp() {
    if (!moving) return;
    setBusyId(moving.id);
    setActionError(null);
    setSuccessMsg(null);
    try {
      const updated = await apiFetch<JobApplication>(
        `/recruitment/applications/${moving.id}/move`,
        {
          method: "POST",
          body: JSON.stringify({ to_stage: toStage, note: moveNote.trim() || null }),
        }
      );
      setApps((list) =>
        list.map((x) => (x.id === moving.id ? { ...x, status: updated.status } : x))
      );
      setMoving(null);
      setMoveNote("");
      setSuccessMsg(
        `Lamaran ${moving.candidateName} dipindah ke tahap "${STAGE_LABEL[toStage] ?? toStage}".`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal memindah tahap.");
    } finally {
      setBusyId(null);
    }
  }

  async function scheduleInterview() {
    if (!scheduling) return;
    if (!ivAt) {
      setActionError("Jadwal wawancara wajib diisi.");
      return;
    }
    const ids: string[] = [];
    if (me) ids.push(me.id);
    const extra = ivExtra
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    ids.push(...extra);
    if (ids.length === 0) {
      setActionError("Minimal satu interviewer wajib diisi.");
      return;
    }
    setBusyId(scheduling.id);
    setActionError(null);
    try {
      await apiFetch<Interview>("/recruitment/interviews", {
        method: "POST",
        body: JSON.stringify({
          application_id: scheduling.id,
          scheduled_at: new Date(ivAt).toISOString(),
          interviewer_ids: ids,
          location: ivLoc.trim() || null,
          mode: ivMode,
        }),
      });
      setScheduling(null);
      setIvAt("");
      setIvLoc("");
      setIvExtra("");
      setSuccessMsg(`Wawancara untuk ${scheduling.candidateName} dijadwalkan.`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menjadwalkan wawancara.");
    } finally {
      setBusyId(null);
    }
  }

  // Kandidat yang belum melamar lowongan ini (hindari 422 duplikat).
  const availableCandidates = useMemo(() => {
    const appliedIds = new Set(apps.map((a) => a.candidate_id));
    return candidates.filter((c) => !appliedIds.has(c.id));
  }, [candidates, apps]);

  function openAdd() {
    setActionError(null);
    setSuccessMsg(null);
    setAddCandId(availableCandidates[0]?.id ?? "");
    setAdding(true);
  }

  async function addApplication() {
    if (!addCandId) {
      setActionError("Pilih kandidat terlebih dahulu.");
      return;
    }
    setBusyId("add");
    setActionError(null);
    setSuccessMsg(null);
    try {
      const created = await apiFetch<JobApplication>("/recruitment/applications", {
        method: "POST",
        body: JSON.stringify({ posting_id: id, candidate_id: addCandId }),
      });
      const cand = candidates.find((c) => c.id === addCandId);
      setApps((list) => [
        ...list,
        {
          ...created,
          candidateName: cand?.name ?? "—",
          candidateEmail: cand?.email ?? "—",
        },
      ]);
      setAdding(false);
      setSuccessMsg(
        `Lamaran ${cand?.name ?? "kandidat"} ditambahkan ke tahap "Dilamar".`
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal menambahkan pelamar."
      );
    } finally {
      setBusyId(null);
    }
  }

  async function postingAction(action: "publish" | "close") {    if (!posting) return;
    setBusyId(posting.id);
    setActionError(null);
    try {
      const updated = await apiFetch<JobPosting>(
        `/recruitment/postings/${posting.id}/${action}`,
        { method: "POST" }
      );
      setPosting(updated);
      setSuccessMsg(
        action === "publish" ? "Lowongan dipublish ke halaman karir." : "Lowongan ditutup."
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!posting) return <EmptyState message="Lowongan tidak ditemukan." />;

  return (
    <div>
      <PageHeader
        title={posting.title}
        subtitle={`Status: ${POSTING_STATUS_LABEL[posting.status] ?? posting.status}${
          posting.published_at ? ` · Tayang ${tanggal(posting.published_at)}` : ""
        }`}
        action={
          <div className="flex gap-2">
            <Link href="/rekrutmen/lowongan" className={btnSecondary}>
              ← Kembali
            </Link>
            {posting.status === "draft" && (
              <button
                className={btnPrimary}
                disabled={busyId === posting.id}
                onClick={() => postingAction("publish")}
              >
                Publish
              </button>
            )}
            {posting.status === "published" && (
              <>
                <button className={btnPrimary} onClick={openAdd}>
                  + Tambah pelamar
                </button>
                <button
                  className={btnSecondary}
                  disabled={busyId === posting.id}
                  onClick={() => postingAction("close")}
                >
                  Tutup
                </button>
              </>
            )}
          </div>
        }
      />

      {successMsg && (
        <div className="mb-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200">
          {successMsg}
        </div>
      )}
      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
          {actionError}
        </div>
      )}

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 lg:col-span-2">
          <h3 className="mb-2 text-sm font-semibold text-slate-500">Deskripsi</h3>
          <p className="whitespace-pre-wrap text-sm text-slate-800">
            {posting.description || "—"}
          </p>
          <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-500">Persyaratan</h3>
          <p className="whitespace-pre-wrap text-sm text-slate-800">
            {posting.requirements || "—"}
          </p>
        </div>
        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Tipe</dt>
              <dd className="font-medium">{posting.employment_type}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Lokasi</dt>
              <dd className="font-medium">{posting.location ?? "—"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Total pelamar</dt>
              <dd className="font-medium">{apps.length}</dd>
            </div>
          </dl>
          <Link
            href={`/karir/${posting.id}`}
            target="_blank"
            className="mt-4 inline-block text-sm font-medium text-brand-700 hover:underline"
          >
            Lihat halaman karir publik ↗
          </Link>
        </div>
      </div>

      <h2 className="mb-3 text-lg font-semibold">Pipeline pelamar</h2>
      {apps.length === 0 ? (
        <EmptyState message="Belum ada pelamar untuk lowongan ini." />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {STAGES.map((s) => (
            <div key={s} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
              <p className="mb-2 text-sm font-semibold text-slate-700">
                {STAGE_LABEL[s]} <span className="text-slate-400">({grouped[s].length})</span>
              </p>
              <div className="space-y-2">
                {grouped[s].map((a) => (
                  <div key={a.id} className="rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200">
                    <Link
                      href={`/rekrutmen/kandidat/${a.candidate_id}`}
                      className="text-sm font-medium text-brand-700 hover:underline"
                    >
                      {a.candidateName}
                    </Link>
                    <p className="text-xs text-slate-500">{a.candidateEmail}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      Dilamar {tanggal(a.applied_at)}
                    </p>
                    {!["hired", "rejected", "withdrawn"].includes(a.status) && (
                      <div className="mt-2 flex gap-1.5">
                        <button
                          className={`${btnSmall} bg-brand-100 text-brand-800 hover:bg-brand-200`}
                          onClick={() => {
                            setMoving(a);
                            setToStage("screening");
                            setMoveNote("");
                          }}
                        >
                          Pindah
                        </button>
                        <button
                          className={`${btnSmall} bg-slate-100 text-slate-700 hover:bg-slate-200`}
                          onClick={() => setScheduling(a)}
                        >
                          Interview
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {adding && (
        <Modal
          title="Tambah pelamar"
          onClose={() => setAdding(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setAdding(false)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === "add" || availableCandidates.length === 0}
                onClick={addApplication}
              >
                {busyId === "add" ? "…" : "Tambahkan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              Tautkan kandidat yang sudah ada ke lowongan{" "}
              <strong>{posting.title}</strong>. Lamaran dibuat di tahap "Dilamar".
            </p>
            {availableCandidates.length === 0 ? (
              <p className="text-sm text-slate-500">
                Semua kandidat sudah melamar lowongan ini.
              </p>
            ) : (
              <Field label="Kandidat" required>
                <select
                  value={addCandId}
                  onChange={(e) => setAddCandId(e.target.value)}
                  className={inputCls}
                >
                  {availableCandidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} — {c.email}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
        </Modal>
      )}

      {moving && (
        <Modal
          title="Pindah tahap lamaran"
          onClose={() => setMoving(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setMoving(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === moving.id}
                onClick={moveApp}
              >
                {busyId === moving.id ? "…" : "Pindahkan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p>
              <strong>{moving.candidateName}</strong> saat ini di tahap{" "}
              <strong>{STAGE_LABEL[moving.status] ?? moving.status}</strong>.
            </p>
            <Field label="Tahap tujuan" required>
              <select value={toStage} onChange={(e) => setToStage(e.target.value)} className={inputCls}>
                {STAGES.filter((s) => s !== moving.status).map((s) => (
                  <option key={s} value={s}>
                    {STAGE_LABEL[s]}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Catatan"
              hint="Wajib diisi bila tahap tujuan mundur dari tahap saat ini."
            >
              <textarea
                value={moveNote}
                onChange={(e) => setMoveNote(e.target.value)}
                className={inputCls}
                rows={3}
              />
            </Field>
          </div>
        </Modal>
      )}

      {scheduling && (
        <Modal
          title="Jadwalkan wawancara"
          onClose={() => setScheduling(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setScheduling(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === scheduling.id}
                onClick={scheduleInterview}
              >
                {busyId === scheduling.id ? "…" : "Jadwalkan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p>
              Kandidat: <strong>{scheduling.candidateName}</strong>
            </p>
            <Field label="Jadwal" required>
              <input
                type="datetime-local"
                value={ivAt}
                onChange={(e) => setIvAt(e.target.value)}
                className={inputCls}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Mode">
                <select value={ivMode} onChange={(e) => setIvMode(e.target.value)} className={inputCls}>
                  <option value="onsite">Onsite</option>
                  <option value="online">Online</option>
                </select>
              </Field>
              <Field label="Lokasi">
                <input
                  value={ivLoc}
                  onChange={(e) => setIvLoc(e.target.value)}
                  className={inputCls}
                  placeholder="mis. Ruang Rapat A / Zoom"
                />
              </Field>
            </div>
            <Field
              label="Interviewer tambahan (UUID, pisahkan koma)"
              hint={`Anda (${me?.full_name ?? "…"}) otomatis menjadi interviewer.`}
            >
              <input
                value={ivExtra}
                onChange={(e) => setIvExtra(e.target.value)}
                className={inputCls}
                placeholder="opsional"
              />
            </Field>
          </div>
        </Modal>
      )}
    </div>
  );
}
