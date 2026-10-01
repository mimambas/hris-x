"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch, apiDownload, apiUpload, ApiError } from "@/lib/api";
import type {
  Candidate,
  JobApplication,
  JobPosting,
  Interview,
  InterviewFeedback,
  Offer,
  OrgUnit,
  Job,
  Location,
  LegalEntity,
  Me,
} from "@/lib/types";
import { tanggal, tanggalWaktu, rupiah } from "@/lib/format";
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
  btnDanger,
  btnSmall,
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

const STAGES = Object.keys(STAGE_LABEL);

const REC_LABEL: Record<string, string> = {
  hire: "Disarankan hire",
  consider: "Pertimbangkan",
  no_hire: "Tidak disarankan",
};

const OFFER_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  sent: "Terkirim",
  accepted: "Diterima",
  declined: "Ditolak",
  expired: "Kedaluwarsa",
};

interface AppView extends JobApplication {
  postingTitle: string;
}

export default function KandidatDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [apps, setApps] = useState<AppView[]>([]);
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [feedbacks, setFeedbacks] = useState<Record<string, InterviewFeedback[]>>({});
  const [offers, setOffers] = useState<Offer[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [units, setUnits] = useState<OrgUnit[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [entities, setEntities] = useState<LegalEntity[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Modal pindah tahap
  const [moving, setMoving] = useState<AppView | null>(null);
  const [toStage, setToStage] = useState("screening");
  const [moveNote, setMoveNote] = useState("");

  // Modal jadwal interview
  const [scheduling, setScheduling] = useState<AppView | null>(null);
  const [ivAt, setIvAt] = useState("");
  const [ivMode, setIvMode] = useState("onsite");
  const [ivLoc, setIvLoc] = useState("");
  const [ivExtra, setIvExtra] = useState("");

  // Form feedback per interview
  const [fbOpen, setFbOpen] = useState<string | null>(null);
  const [fbInterviewer, setFbInterviewer] = useState("");
  const [fbScore, setFbScore] = useState("4");
  const [fbRec, setFbRec] = useState("hire");
  const [fbNotes, setFbNotes] = useState("");

  // Form offer
  const [offerFormFor, setOfferFormFor] = useState<AppView | null>(null);
  const [oSalary, setOSalary] = useState("");
  const [oStart, setOStart] = useState("");
  const [oContract, setOContract] = useState("PKWTT");
  const [oExpires, setOExpires] = useState("");
  const [oJob, setOJob] = useState("");
  const [oUnit, setOUnit] = useState("");
  const [oLoc, setOLoc] = useState("");
  const [oEntity, setOEntity] = useState("");

  // Tolak offer
  const [declining, setDeclining] = useState<Offer | null>(null);
  const [declineNote, setDeclineNote] = useState("");

  // Upload CV
  const [uploading, setUploading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [cands, allApps, postings, ivs, ofs, m, jb, un, lc, le] =
        await Promise.all([
          apiFetch<Candidate[]>("/recruitment/candidates"),
          apiFetch<JobApplication[]>("/recruitment/applications"),
          apiFetch<JobPosting[]>("/recruitment/postings"),
          apiFetch<Interview[]>("/recruitment/interviews"),
          apiFetch<Offer[]>("/recruitment/offers"),
          apiFetch<Me>("/me"),
          apiFetch<Job[]>("/org/jobs"),
          apiFetch<OrgUnit[]>("/org/units"),
          apiFetch<Location[]>("/org/locations"),
          apiFetch<LegalEntity[]>("/org/legal-entities"),
        ]);
      const cand = cands.find((c) => c.id === id) ?? null;
      setCandidate(cand);
      const postMap = new Map(postings.map((p) => [p.id, p.title]));
      const myApps = allApps
        .filter((a) => a.candidate_id === id)
        .map((a) => ({ ...a, postingTitle: postMap.get(a.posting_id) ?? "—" }));
      setApps(myApps);
      const appIds = new Set(myApps.map((a) => a.id));
      setInterviews(ivs.filter((v) => appIds.has(v.application_id)));
      setOffers(ofs.filter((o) => appIds.has(o.application_id)));
      const fb: Record<string, InterviewFeedback[]> = {};
      await Promise.all(
        ivs
          .filter((v) => appIds.has(v.application_id))
          .map(async (v) => {
            try {
              fb[v.id] = await apiFetch<InterviewFeedback[]>(
                `/recruitment/interviews/${v.id}/feedback`
              );
            } catch {
              fb[v.id] = [];
            }
          })
      );
      setFeedbacks(fb);
      setMe(m);
      setJobs(jb);
      setUnits(un);
      setLocations(lc);
      setEntities(le);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat detail kandidat.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const offerFor = (appId: string) => offers.find((o) => o.application_id === appId);
  const interviewsFor = (appId: string) =>
    interviews.filter((v) => v.application_id === appId);
  const interviewerLabel = (uid: string) =>
    me && uid === me.id ? `${me.full_name} (Anda)` : uid.slice(0, 8);

  async function moveApp() {
    if (!moving) return;
    setBusyId(moving.id);
    setActionError(null);
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
      setSuccessMsg(`Tahap lamaran dipindah ke "${STAGE_LABEL[toStage] ?? toStage}".`);
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
    ids.push(...ivExtra.split(",").map((s) => s.trim()).filter(Boolean));
    setBusyId(scheduling.id);
    setActionError(null);
    try {
      const created = await apiFetch<Interview>("/recruitment/interviews", {
        method: "POST",
        body: JSON.stringify({
          application_id: scheduling.id,
          scheduled_at: new Date(ivAt).toISOString(),
          interviewer_ids: ids,
          location: ivLoc.trim() || null,
          mode: ivMode,
        }),
      });
      setInterviews((list) => [...list, created]);
      setScheduling(null);
      setIvAt("");
      setIvLoc("");
      setIvExtra("");
      setSuccessMsg("Wawancara dijadwalkan.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menjadwalkan wawancara.");
    } finally {
      setBusyId(null);
    }
  }

  async function interviewAction(iv: Interview, action: "complete" | "cancel") {
    setBusyId(iv.id);
    setActionError(null);
    try {
      const updated = await apiFetch<Interview>(
        `/recruitment/interviews/${iv.id}/${action}`,
        { method: "POST" }
      );
      setInterviews((list) => list.map((x) => (x.id === iv.id ? updated : x)));
      setSuccessMsg(
        action === "complete" ? "Wawancara ditandai selesai." : "Wawancara dibatalkan."
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  async function submitFeedback(iv: Interview) {
    if (!fbInterviewer) {
      setActionError("Pilih interviewer yang memberi feedback.");
      return;
    }
    const score = parseInt(fbScore, 10);
    setBusyId(iv.id);
    setActionError(null);
    try {
      const created = await apiFetch<InterviewFeedback>(
        `/recruitment/interviews/${iv.id}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({
            interviewer_id: fbInterviewer,
            score,
            notes: fbNotes.trim() || null,
            recommendation: fbRec,
          }),
        }
      );
      setFeedbacks((m) => ({ ...m, [iv.id]: [...(m[iv.id] ?? []), created] }));
      setFbOpen(null);
      setFbNotes("");
      setSuccessMsg("Feedback wawancara tersimpan.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menyimpan feedback.");
    } finally {
      setBusyId(null);
    }
  }

  async function createOffer() {
    if (!offerFormFor) return;
    const salary = parseInt(oSalary, 10);
    if (!Number.isFinite(salary) || salary <= 0) {
      setActionError("Gaji harus angka positif.");
      return;
    }
    if (!oStart || !oExpires || !oJob || !oUnit || !oLoc || !oEntity) {
      setActionError("Semua field offer wajib diisi.");
      return;
    }
    setBusyId(offerFormFor.id);
    setActionError(null);
    try {
      const created = await apiFetch<Offer>("/recruitment/offers", {
        method: "POST",
        body: JSON.stringify({
          application_id: offerFormFor.id,
          salary,
          start_date: oStart,
          contract_type: oContract.trim(),
          expires_at: new Date(oExpires).toISOString(),
          job_id: oJob,
          org_unit_id: oUnit,
          location_id: oLoc,
          legal_entity_id: oEntity,
        }),
      });
      setOffers((list) => [...list, created]);
      setOfferFormFor(null);
      setSuccessMsg("E-offer dibuat (draf). Klik Kirim untuk mengirim ke kandidat.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal membuat offer.");
    } finally {
      setBusyId(null);
    }
  }

  async function sendOffer(o: Offer) {
    setBusyId(o.id);
    setActionError(null);
    try {
      const updated = await apiFetch<Offer>(`/recruitment/offers/${o.id}/send`, {
        method: "POST",
      });
      setOffers((list) => list.map((x) => (x.id === o.id ? updated : x)));
      setSuccessMsg("Offer dikirim. Bagikan tautan publik ke kandidat.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal mengirim offer.");
    } finally {
      setBusyId(null);
    }
  }

  async function declineOffer() {
    if (!declining) return;
    setBusyId(declining.id);
    setActionError(null);
    try {
      const updated = await apiFetch<Offer>(`/recruitment/offers/${declining.id}/decline`, {
        method: "POST",
        body: JSON.stringify({ note: declineNote.trim() || null }),
      });
      setOffers((list) => list.map((x) => (x.id === declining.id ? updated : x)));
      setDeclining(null);
      setDeclineNote("");
      setSuccessMsg("Offer ditandai ditolak kandidat.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menolak offer.");
    } finally {
      setBusyId(null);
    }
  }

  async function downloadPdf(o: Offer) {
    try {
      await apiDownload(`/recruitment/offers/${o.id}/pdf`, `offer_${o.id.slice(0, 8)}.pdf`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal mengunduh PDF.");
    }
  }

  async function uploadCv(file: File) {
    if (!candidate) return;
    setUploading(true);
    setActionError(null);
    try {
      const updated = await apiUpload<Candidate>(
        `/recruitment/candidates/${candidate.id}/cv`,
        file
      );
      setCandidate(updated);
      setSuccessMsg("CV berhasil diunggah.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal mengunggah CV.");
    } finally {
      setUploading(false);
    }
  }

  async function downloadCv() {
    if (!candidate) return;
    try {
      await apiDownload(
        `/recruitment/candidates/${candidate.id}/cv/download`,
        `cv_${candidate.name}.pdf`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal mengunduh CV.");
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!candidate) return <EmptyState message="Kandidat tidak ditemukan." />;

  return (
    <div>
      <PageHeader
        title={candidate.name}
        subtitle={`${candidate.email}${candidate.phone ? ` · ${candidate.phone}` : ""}`}
        action={
          <Link href="/rekrutmen/kandidat" className={btnSecondary}>
            ← Kembali
          </Link>
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

      <div className="mb-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <p className="text-xs text-slate-500">Sumber</p>
            <p className="text-sm font-medium">{candidate.source}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">CV</p>
            {candidate.cv_file_path ? (
              <button
                onClick={downloadCv}
                className="text-sm font-medium text-brand-700 hover:underline"
              >
                Unduh CV
              </button>
            ) : (
              <p className="text-sm text-slate-400">Belum ada</p>
            )}
          </div>
          <div>
            <p className="text-xs text-slate-500">Unggah CV (PDF/JPG/PNG/DOC, maks 10 MB)</p>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadCv(f);
                e.target.value = "";
              }}
              className="mt-1 text-sm"
            />
          </div>
        </div>
      </div>

      <h2 className="mb-3 text-lg font-semibold">Lamaran ({apps.length})</h2>
      {apps.length === 0 ? (
        <EmptyState message="Kandidat ini belum melamar lowongan apa pun." />
      ) : (
        <div className="space-y-4">
          {apps.map((a) => {
            const ivs = interviewsFor(a.id);
            const offer = offerFor(a.id);
            const final = ["hired", "rejected", "withdrawn"].includes(a.status);
            return (
              <div key={a.id} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-semibold text-slate-900">{a.postingTitle}</p>
                    <p className="text-xs text-slate-500">
                      Dilamar {tanggal(a.applied_at)} · Tahap:{" "}
                      <strong>{STAGE_LABEL[a.status] ?? a.status}</strong>
                    </p>
                  </div>
                  {!final && (
                    <button
                      className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                      onClick={() => {
                        setMoving(a);
                        setToStage("screening");
                        setMoveNote("");
                      }}
                    >
                      Pindah tahap
                    </button>
                  )}
                </div>

                {/* Wawancara */}
                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-700">
                      Wawancara ({ivs.length})
                    </h3>
                    {!final && (
                      <button
                        className={`${btnSmall} bg-slate-100 text-slate-700 hover:bg-slate-200`}
                        onClick={() => setScheduling(a)}
                      >
                        ＋ Jadwalkan
                      </button>
                    )}
                  </div>
                  {ivs.length === 0 ? (
                    <p className="text-sm text-slate-400">Belum ada wawancara.</p>
                  ) : (
                    <div className="space-y-3">
                      {ivs.map((iv) => (
                        <div key={iv.id} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-medium">
                              {tanggalWaktu(iv.scheduled_at)} · {iv.mode} · {iv.location ?? "—"}
                            </p>
                            <span className="text-xs text-slate-500">
                              {iv.status === "scheduled"
                                ? "Terjadwal"
                                : iv.status === "completed"
                                  ? "Selesai"
                                  : "Dibatalkan"}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">
                            Interviewer: {iv.interviewer_ids.map(interviewerLabel).join(", ")}
                          </p>
                          {(feedbacks[iv.id] ?? []).length > 0 && (
                            <div className="mt-2 space-y-1">
                              {(feedbacks[iv.id] ?? []).map((fb) => (
                                <div key={fb.id} className="rounded bg-white p-2 text-xs ring-1 ring-slate-200">
                                  <p>
                                    <strong>Skor {fb.score}/5</strong> · {REC_LABEL[fb.recommendation] ?? fb.recommendation} ·{" "}
                                    {interviewerLabel(fb.interviewer_id)}
                                  </p>
                                  {fb.notes && <p className="mt-0.5 text-slate-600">{fb.notes}</p>}
                                </div>
                              ))}
                            </div>
                          )}
                          {iv.status === "scheduled" && (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              <button
                                className={`${btnSmall} bg-green-600 text-white hover:bg-green-700`}
                                disabled={busyId === iv.id}
                                onClick={() => interviewAction(iv, "complete")}
                              >
                                Selesaikan
                              </button>
                              <button
                                className={`${btnSmall} bg-slate-200 text-slate-700 hover:bg-slate-300`}
                                disabled={busyId === iv.id}
                                onClick={() => interviewAction(iv, "cancel")}
                              >
                                Batalkan
                              </button>
                              <button
                                className={`${btnSmall} bg-brand-100 text-brand-800 hover:bg-brand-200`}
                                onClick={() => {
                                  setFbOpen(iv.id);
                                  setFbInterviewer(
                                    me && iv.interviewer_ids.includes(me.id) ? me.id : iv.interviewer_ids[0] ?? ""
                                  );
                                  setFbScore("4");
                                  setFbRec("hire");
                                  setFbNotes("");
                                }}
                              >
                                ＋ Feedback
                              </button>
                            </div>
                          )}
                          {fbOpen === iv.id && (
                            <div className="mt-3 space-y-2 rounded-lg bg-white p-3 ring-1 ring-slate-200">
                              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                                <Field label="Interviewer" required>
                                  <select
                                    value={fbInterviewer}
                                    onChange={(e) => setFbInterviewer(e.target.value)}
                                    className={inputCls}
                                  >
                                    <option value="">— Pilih —</option>
                                    {iv.interviewer_ids.map((uid) => (
                                      <option key={uid} value={uid}>
                                        {interviewerLabel(uid)}
                                      </option>
                                    ))}
                                  </select>
                                </Field>
                                <Field label="Skor (1–5)" required>
                                  <select
                                    value={fbScore}
                                    onChange={(e) => setFbScore(e.target.value)}
                                    className={inputCls}
                                  >
                                    {[1, 2, 3, 4, 5].map((n) => (
                                      <option key={n} value={n}>
                                        {n}
                                      </option>
                                    ))}
                                  </select>
                                </Field>
                                <Field label="Rekomendasi" required>
                                  <select
                                    value={fbRec}
                                    onChange={(e) => setFbRec(e.target.value)}
                                    className={inputCls}
                                  >
                                    {Object.entries(REC_LABEL).map(([v, l]) => (
                                      <option key={v} value={v}>
                                        {l}
                                      </option>
                                    ))}
                                  </select>
                                </Field>
                              </div>
                              <Field label="Catatan">
                                <textarea
                                  value={fbNotes}
                                  onChange={(e) => setFbNotes(e.target.value)}
                                  className={inputCls}
                                  rows={2}
                                />
                              </Field>
                              <div className="flex gap-2">
                                <button
                                  className={btnPrimary}
                                  disabled={busyId === iv.id}
                                  onClick={() => submitFeedback(iv)}
                                >
                                  {busyId === iv.id ? "…" : "Simpan feedback"}
                                </button>
                                <button className={btnSecondary} onClick={() => setFbOpen(null)}>
                                  Batal
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* E-offer */}
                {a.status === "offering" && (
                  <div className="mt-4 rounded-lg bg-amber-50 p-4 ring-1 ring-amber-200">
                    <h3 className="text-sm font-semibold text-slate-700">E-Offer</h3>
                    {!offer ? (
                      <button
                        className={`${btnSmall} mt-2 bg-amber-600 text-white hover:bg-amber-700`}
                        onClick={() => setOfferFormFor(a)}
                      >
                        ＋ Buat offer
                      </button>
                    ) : (
                      <div className="mt-2 text-sm">
                        <p>
                          Status: <strong>{OFFER_STATUS_LABEL[offer.status] ?? offer.status}</strong> ·{" "}
                          Gaji {rupiah(offer.salary)} · Mulai {tanggal(offer.start_date)} · Berakhir{" "}
                          {tanggalWaktu(offer.expires_at)}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {offer.status === "draft" && (
                            <button
                              className={`${btnSmall} bg-green-600 text-white hover:bg-green-700`}
                              disabled={busyId === offer.id}
                              onClick={() => sendOffer(offer)}
                            >
                              {busyId === offer.id ? "…" : "Kirim ke kandidat"}
                            </button>
                          )}
                          <button
                            className={`${btnSmall} bg-slate-200 text-slate-700 hover:bg-slate-300`}
                            onClick={() => downloadPdf(offer)}
                          >
                            Unduh PDF
                          </button>
                          {offer.status === "sent" && (
                            <button
                              className={`${btnSmall} bg-red-100 text-red-700 hover:bg-red-200`}
                              onClick={() => {
                                setDeclining(offer);
                                setDeclineNote("");
                              }}
                            >
                              Tandai ditolak
                            </button>
                          )}
                        </div>
                        {offer.offer_token && (
                          <p className="mt-2 break-all text-xs text-slate-600">
                            Tautan publik kandidat:{" "}
                            <Link
                              href={`/offer/${offer.offer_token}`}
                              target="_blank"
                              className="font-medium text-brand-700 hover:underline"
                            >
                              {typeof window !== "undefined" ? window.location.origin : ""}/offer/
                              {offer.offer_token.slice(0, 20)}…
                            </Link>
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
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
              <button className={btnPrimary} disabled={busyId === moving.id} onClick={moveApp}>
                {busyId === moving.id ? "…" : "Pindahkan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p>
              Saat ini di tahap <strong>{STAGE_LABEL[moving.status] ?? moving.status}</strong>.
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
            <Field label="Catatan" hint="Wajib diisi bila tahap tujuan mundur.">
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
                <input value={ivLoc} onChange={(e) => setIvLoc(e.target.value)} className={inputCls} />
              </Field>
            </div>
            <Field
              label="Interviewer tambahan (UUID, pisahkan koma)"
              hint={`Anda (${me?.full_name ?? "…"}) otomatis menjadi interviewer.`}
            >
              <input value={ivExtra} onChange={(e) => setIvExtra(e.target.value)} className={inputCls} />
            </Field>
          </div>
        </Modal>
      )}

      {offerFormFor && (
        <Modal
          title="Buat e-offer"
          onClose={() => setOfferFormFor(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setOfferFormFor(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === offerFormFor.id}
                onClick={createOffer}
              >
                {busyId === offerFormFor.id ? "…" : "Buat draf offer"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Gaji (Rp)" required>
                <input
                  type="number"
                  min={1}
                  value={oSalary}
                  onChange={(e) => setOSalary(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Tanggal mulai" required>
                <input
                  type="date"
                  value={oStart}
                  onChange={(e) => setOStart(e.target.value)}
                  className={inputCls}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Tipe kontrak" required>
                <input
                  value={oContract}
                  onChange={(e) => setOContract(e.target.value)}
                  className={inputCls}
                  placeholder="PKWTT / PKWT"
                />
              </Field>
              <Field label="Berlaku hingga" required>
                <input
                  type="datetime-local"
                  value={oExpires}
                  onChange={(e) => setOExpires(e.target.value)}
                  className={inputCls}
                />
              </Field>
            </div>
            <Field label="Jabatan" required>
              <select value={oJob} onChange={(e) => setOJob(e.target.value)} className={inputCls}>
                <option value="">— Pilih —</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Unit organisasi" required>
              <select value={oUnit} onChange={(e) => setOUnit(e.target.value)} className={inputCls}>
                <option value="">— Pilih —</option>
                {units.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Lokasi" required>
                <select value={oLoc} onChange={(e) => setOLoc(e.target.value)} className={inputCls}>
                  <option value="">— Pilih —</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Legal entity" required>
                <select value={oEntity} onChange={(e) => setOEntity(e.target.value)} className={inputCls}>
                  <option value="">— Pilih —</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </div>
        </Modal>
      )}

      {declining && (
        <Modal
          title="Tandai offer ditolak"
          onClose={() => setDeclining(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setDeclining(null)}>
                Batal
              </button>
              <button
                className={btnDanger}
                disabled={busyId === declining.id}
                onClick={declineOffer}
              >
                {busyId === declining.id ? "…" : "Tandai ditolak"}
              </button>
            </>
          }
        >
          <Field label="Catatan">
            <textarea
              value={declineNote}
              onChange={(e) => setDeclineNote(e.target.value)}
              className={inputCls}
              rows={3}
              placeholder="mis. kandidat menerima tawaran lain"
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
