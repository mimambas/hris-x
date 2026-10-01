"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type { Requisition, JobPosting, OrgUnit } from "@/lib/types";
import { tanggal } from "@/lib/format";
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

const REQ_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  submitted: "Diajukan",
  approved: "Disetujui",
  rejected: "Ditolak",
};

const POSTING_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  published: "Tayang",
  closed: "Ditutup",
};

const TIPE_PEKERJAAN = ["tetap", "kontrak", "magang", "harian", "paruh_waktu"];

function StatusBadge({ label, tone }: { label: string; tone: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

function reqTone(s: string): string {
  if (s === "approved") return "bg-green-100 text-green-800";
  if (s === "rejected") return "bg-red-100 text-red-800";
  if (s === "submitted") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-700";
}

function postingTone(s: string): string {
  if (s === "published") return "bg-green-100 text-green-800";
  if (s === "closed") return "bg-slate-200 text-slate-600";
  return "bg-amber-100 text-amber-800";
}

export default function LowonganPage() {
  const [tab, setTab] = useState<"req" | "posting">("req");
  const [reqs, setReqs] = useState<Requisition[]>([]);
  const [postings, setPostings] = useState<JobPosting[]>([]);
  const [units, setUnits] = useState<OrgUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Form requisition
  const [showReqForm, setShowReqForm] = useState(false);
  const [fUnit, setFUnit] = useState("");
  const [fTitle, setFTitle] = useState("");
  const [fHeadcount, setFHeadcount] = useState("1");
  const [fReason, setFReason] = useState("");

  // Keputusan requisition (setujui/tolak)
  const [deciding, setDeciding] = useState<Requisition | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  // Form posting
  const [showPostingForm, setShowPostingForm] = useState(false);
  const [pReq, setPReq] = useState("");
  const [pTitle, setPTitle] = useState("");
  const [pDesc, setPDesc] = useState("");
  const [pReqs, setPReqs] = useState("");
  const [pType, setPType] = useState("tetap");
  const [pLoc, setPLoc] = useState("");
  const [postingFilter, setPostingFilter] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [r, p, u] = await Promise.all([
        apiFetch<Requisition[]>("/recruitment/requisitions"),
        apiFetch<JobPosting[]>("/recruitment/postings"),
        apiFetch<OrgUnit[]>("/org/units"),
      ]);
      setReqs(r);
      setPostings(p);
      setUnits(u);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data rekrutmen.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const unitName = (id: string) => units.find((u) => u.id === id)?.name ?? "—";
  const approvedReqs = reqs.filter((r) => r.status === "approved");
  const filteredPostings = postingFilter
    ? postings.filter((p) => p.status === postingFilter)
    : postings;

  async function createReq() {
    if (!fUnit || !fTitle.trim()) {
      setActionError("Unit organisasi dan nama jabatan wajib diisi.");
      return;
    }
    const n = parseInt(fHeadcount, 10);
    if (!Number.isFinite(n) || n < 1) {
      setActionError("Jumlah kebutuhan harus minimal 1.");
      return;
    }
    setBusyId("new-req");
    setActionError(null);
    try {
      const created = await apiFetch<Requisition>("/recruitment/requisitions", {
        method: "POST",
        body: JSON.stringify({
          org_unit_id: fUnit,
          job_title: fTitle.trim(),
          headcount: n,
          reason: fReason.trim() || null,
        }),
      });
      setReqs((list) => [created, ...list]);
      setShowReqForm(false);
      setFUnit("");
      setFTitle("");
      setFHeadcount("1");
      setFReason("");
      setSuccessMsg(`Requisition "${created.job_title}" dibuat (draf).`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal membuat requisition.");
    } finally {
      setBusyId(null);
    }
  }

  async function reqAction(r: Requisition, action: "submit" | "approve" | "reject") {
    if (action !== "submit" && !decisionNote.trim() && action === "reject") {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    setBusyId(r.id);
    setActionError(null);
    setSuccessMsg(null);
    try {
      const updated = await apiFetch<Requisition>(
        `/recruitment/requisitions/${r.id}/${action}`,
        {
          method: "POST",
          body: JSON.stringify(
            action === "submit" ? {} : { note: decisionNote.trim() || null }
          ),
        }
      );
      setReqs((list) => list.map((x) => (x.id === r.id ? updated : x)));
      setDeciding(null);
      setDecisionNote("");
      const msg =
        action === "submit"
          ? "diajukan ke HR"
          : action === "approve"
            ? "disetujui"
            : "ditolak";
      setSuccessMsg(`Requisition "${r.job_title}" ${msg}.`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  async function createPosting() {
    if (!pReq || !pTitle.trim()) {
      setActionError("Requisition dan judul lowongan wajib diisi.");
      return;
    }
    setBusyId("new-posting");
    setActionError(null);
    try {
      const created = await apiFetch<JobPosting>("/recruitment/postings", {
        method: "POST",
        body: JSON.stringify({
          requisition_id: pReq,
          title: pTitle.trim(),
          description: pDesc.trim() || null,
          requirements: pReqs.trim() || null,
          employment_type: pType,
          location: pLoc.trim() || null,
        }),
      });
      setPostings((list) => [created, ...list]);
      setShowPostingForm(false);
      setPReq("");
      setPTitle("");
      setPDesc("");
      setPReqs("");
      setPType("tetap");
      setPLoc("");
      setSuccessMsg(`Lowongan "${created.title}" dibuat (draf).`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal membuat lowongan.");
    } finally {
      setBusyId(null);
    }
  }

  async function postingAction(p: JobPosting, action: "publish" | "close") {
    setBusyId(p.id);
    setActionError(null);
    setSuccessMsg(null);
    try {
      const updated = await apiFetch<JobPosting>(
        `/recruitment/postings/${p.id}/${action}`,
        { method: "POST" }
      );
      setPostings((list) => list.map((x) => (x.id === p.id ? updated : x)));
      setSuccessMsg(
        `Lowongan "${p.title}" ${action === "publish" ? "dipublish ke halaman karir." : "ditutup."}`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Rekrutmen"
        subtitle="Kelola kebutuhan pegawai, lowongan, dan pelamar"
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

      <div className="mb-4 flex gap-2 border-b border-slate-200">
        {(["req", "posting"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {t === "req" ? "Kebutuhan (Requisition)" : "Lowongan"}
          </button>
        ))}
        <div className="ml-auto pb-2">
          <Link
            href="/rekrutmen/kandidat"
            className="text-sm font-medium text-brand-700 hover:underline"
          >
            Lihat daftar kandidat →
          </Link>
        </div>
      </div>

      {tab === "req" && (
        <div>
          <div className="mb-4">
            <button className={btnPrimary} onClick={() => setShowReqForm(true)}>
              ＋ Buat requisition
            </button>
          </div>
          {reqs.length === 0 ? (
            <EmptyState message="Belum ada requisition. Buat kebutuhan pegawai baru untuk memulai rekrutmen." />
          ) : (
            <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-500">
                    <th className="px-4 py-3 font-medium">Jabatan</th>
                    <th className="px-4 py-3 font-medium">Unit</th>
                    <th className="px-4 py-3 font-medium">Jumlah</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {reqs.map((r) => (
                    <tr key={r.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-4 py-3 font-medium text-slate-900">{r.job_title}</td>
                      <td className="px-4 py-3 text-slate-600">{unitName(r.org_unit_id)}</td>
                      <td className="px-4 py-3 text-slate-600">{r.headcount} orang</td>
                      <td className="px-4 py-3">
                        <StatusBadge label={REQ_STATUS_LABEL[r.status] ?? r.status} tone={reqTone(r.status)} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {r.status === "draft" && (
                            <button
                              className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                              disabled={busyId === r.id}
                              onClick={() => reqAction(r, "submit")}
                            >
                              {busyId === r.id ? "…" : "Ajukan"}
                            </button>
                          )}
                          {r.status === "submitted" && (
                            <>
                              <button
                                className={`${btnSmall} bg-green-600 text-white hover:bg-green-700`}
                                onClick={() => setDeciding(r)}
                              >
                                Setujui
                              </button>
                              <button
                                className={`${btnSmall} bg-red-100 text-red-700 hover:bg-red-200`}
                                onClick={() => setDeciding(r)}
                              >
                                Tolak
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "posting" && (
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <button className={btnPrimary} onClick={() => setShowPostingForm(true)}>
              ＋ Buat lowongan
            </button>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              Status
              <select
                value={postingFilter}
                onChange={(e) => setPostingFilter(e.target.value)}
                className={inputCls}
              >
                <option value="">Semua</option>
                <option value="draft">Draf</option>
                <option value="published">Tayang</option>
                <option value="closed">Ditutup</option>
              </select>
            </label>
          </div>
          {filteredPostings.length === 0 ? (
            <EmptyState message="Belum ada lowongan pada filter ini." />
          ) : (
            <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-500">
                    <th className="px-4 py-3 font-medium">Judul</th>
                    <th className="px-4 py-3 font-medium">Tipe</th>
                    <th className="px-4 py-3 font-medium">Lokasi</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPostings.map((p) => (
                    <tr key={p.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-4 py-3">
                        <Link
                          href={`/rekrutmen/lowongan/${p.id}`}
                          className="font-medium text-brand-700 hover:underline"
                        >
                          {p.title}
                        </Link>
                        {p.published_at && (
                          <p className="text-xs text-slate-400">
                            Tayang {tanggal(p.published_at)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">{p.employment_type}</td>
                      <td className="px-4 py-3 text-slate-600">{p.location ?? "—"}</td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          label={POSTING_STATUS_LABEL[p.status] ?? p.status}
                          tone={postingTone(p.status)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {p.status === "draft" && (
                            <button
                              className={`${btnSmall} bg-green-600 text-white hover:bg-green-700`}
                              disabled={busyId === p.id}
                              onClick={() => postingAction(p, "publish")}
                              title="Requisition harus sudah disetujui"
                            >
                              {busyId === p.id ? "…" : "Publish"}
                            </button>
                          )}
                          {p.status === "published" && (
                            <button
                              className={`${btnSmall} bg-slate-200 text-slate-700 hover:bg-slate-300`}
                              disabled={busyId === p.id}
                              onClick={() => postingAction(p, "close")}
                            >
                              {busyId === p.id ? "…" : "Tutup"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {showReqForm && (
        <Modal
          title="Buat requisition"
          onClose={() => setShowReqForm(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowReqForm(false)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === "new-req"}
                onClick={createReq}
              >
                {busyId === "new-req" ? "Menyimpan…" : "Simpan draf"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="Unit organisasi" required>
              <select value={fUnit} onChange={(e) => setFUnit(e.target.value)} className={inputCls}>
                <option value="">— Pilih unit —</option>
                {units.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Nama jabatan" required>
              <input
                value={fTitle}
                onChange={(e) => setFTitle(e.target.value)}
                className={inputCls}
                placeholder="mis. UI/UX Designer"
                maxLength={200}
              />
            </Field>
            <Field label="Jumlah kebutuhan" required>
              <input
                type="number"
                min={1}
                value={fHeadcount}
                onChange={(e) => setFHeadcount(e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Alasan">
              <textarea
                value={fReason}
                onChange={(e) => setFReason(e.target.value)}
                className={inputCls}
                rows={3}
                placeholder="mis. ekspansi tim produk"
              />
            </Field>
          </div>
        </Modal>
      )}

      {deciding && (
        <Modal
          title="Keputusan requisition"
          onClose={() => {
            setDeciding(null);
            setDecisionNote("");
          }}
          actions={
            <>
              <button
                className={btnSecondary}
                onClick={() => {
                  setDeciding(null);
                  setDecisionNote("");
                }}
              >
                Batal
              </button>
              <button
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
                disabled={busyId === deciding.id}
                onClick={() => reqAction(deciding, "reject")}
              >
                Tolak
              </button>
              <button
                className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-60"
                disabled={busyId === deciding.id}
                onClick={() => reqAction(deciding, "approve")}
              >
                {busyId === deciding.id ? "…" : "Setujui"}
              </button>
            </>
          }
        >
          <p className="mb-3">
            Requisition <strong>{deciding.job_title}</strong> ({deciding.headcount} orang).
          </p>
          <Field label="Catatan keputusan" hint="Wajib diisi bila menolak.">
            <textarea
              value={decisionNote}
              onChange={(e) => setDecisionNote(e.target.value)}
              className={inputCls}
              rows={3}
            />
          </Field>
        </Modal>
      )}

      {showPostingForm && (
        <Modal
          title="Buat lowongan"
          onClose={() => setShowPostingForm(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowPostingForm(false)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === "new-posting"}
                onClick={createPosting}
              >
                {busyId === "new-posting" ? "Menyimpan…" : "Simpan draf"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="Requisition (harus sudah disetujui)" required>
              <select value={pReq} onChange={(e) => setPReq(e.target.value)} className={inputCls}>
                <option value="">— Pilih requisition —</option>
                {approvedReqs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.job_title} · {unitName(r.org_unit_id)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Judul lowongan" required>
              <input
                value={pTitle}
                onChange={(e) => setPTitle(e.target.value)}
                className={inputCls}
                maxLength={200}
              />
            </Field>
            <Field label="Deskripsi">
              <textarea value={pDesc} onChange={(e) => setPDesc(e.target.value)} className={inputCls} rows={3} />
            </Field>
            <Field label="Persyaratan">
              <textarea value={pReqs} onChange={(e) => setPReqs(e.target.value)} className={inputCls} rows={3} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tipe pekerjaan">
                <select value={pType} onChange={(e) => setPType(e.target.value)} className={inputCls}>
                  {TIPE_PEKERJAAN.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Lokasi">
                <input
                  value={pLoc}
                  onChange={(e) => setPLoc(e.target.value)}
                  className={inputCls}
                  placeholder="mis. Jakarta"
                />
              </Field>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
