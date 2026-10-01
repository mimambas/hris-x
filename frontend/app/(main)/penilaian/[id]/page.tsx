"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import { EmptyState, Modal } from "@/components/ui";

// ---------------------------------------------------------------- tipe data
interface Cycle {
  id: string;
  name: string;
  year: number;
  status: string;
  start_date: string;
  end_date: string;
}

interface Goal {
  id: string;
  employment_id: string;
  cycle_id: string;
  title: string;
  description: string | null;
  weight: number;
  target_text: string | null;
  status: string;
  manager_comment: string | null;
}

interface Appraisal {
  id: string;
  employment_id: string;
  cycle_id: string;
  self_scores: { goal_id: string; score: number; comment?: string }[] | null;
  self_submitted_at: string | null;
  manager_scores: { goal_id: string; score: number }[] | null;
  manager_submitted_at: string | null;
  potential_score: number | null;
  final_score: number | null;
}

interface NineBoxEntry {
  employment_id: string;
  person_name: string;
  final_score: number;
  potential_score: number;
  perf_category: string;
  pot_category: string;
  box_key: string;
  label_id: string;
}

interface NineBox {
  cycle_id: string;
  cycle_name: string;
  boxes: Record<string, NineBoxEntry[]>;
}

interface TrainingRec {
  employment_id: string;
  person_name: string;
  box_key: string;
  label_id: string;
  final_score: number;
  potential_score: number;
  recommended_categories: string[];
  courses: { id: string; code: string; name: string; provider: string | null }[];
}

interface Employment {
  id: string;
  person_id: string;
  status: string;
}

interface Person {
  id: string;
  full_name: string;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  goal_setting: "Penetapan Sasaran",
  mid_year: "Tinjauan Tengah Tahun",
  year_end: "Penilaian Akhir Tahun",
  calibration: "Kalibrasi",
  closed: "Ditutup",
};

const GOAL_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  submitted: "Diajukan",
  approved: "Disetujui",
  rejected: "Ditolak",
};

// Urutan grid 9-box: baris = potensi (Tinggi→Rendah), kolom = kinerja (Rendah→Tinggi)
const GRID: { pot: string; perf: string; key: string }[][] = [
  [
    { pot: "Tinggi", perf: "Rendah", key: "rough_diamond" },
    { pot: "Tinggi", perf: "Sedang", key: "high_potential" },
    { pot: "Tinggi", perf: "Tinggi", key: "star" },
  ],
  [
    { pot: "Sedang", perf: "Rendah", key: "inconsistent_player" },
    { pot: "Sedang", perf: "Sedang", key: "key_player" },
    { pot: "Sedang", perf: "Tinggi", key: "high_performer" },
  ],
  [
    { pot: "Rendah", perf: "Rendah", key: "low_performer" },
    { pot: "Rendah", perf: "Sedang", key: "average_performer" },
    { pot: "Rendah", perf: "Tinggi", key: "trusted_professional" },
  ],
];

const BOX_COLOR: Record<string, string> = {
  star: "bg-emerald-100 border-emerald-300",
  high_performer: "bg-emerald-50 border-emerald-200",
  trusted_professional: "bg-emerald-50 border-emerald-200",
  high_potential: "bg-blue-50 border-blue-200",
  key_player: "bg-blue-50 border-blue-200",
  average_performer: "bg-amber-50 border-amber-200",
  rough_diamond: "bg-amber-50 border-amber-200",
  inconsistent_player: "bg-orange-50 border-orange-200",
  low_performer: "bg-red-50 border-red-200",
};

type Tab = "sasaran" | "penilaian" | "ninebox" | "pelatihan";

export default function PenilaianDetailPage() {
  const params = useParams();
  const cycleId = params.id as string;

  const [cycle, setCycle] = useState<Cycle | null>(null);
  const [tab, setTab] = useState<Tab>("sasaran");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Karyawan
  const [employments, setEmployments] = useState<Employment[]>([]);
  const [personMap, setPersonMap] = useState<Map<string, string>>(new Map());
  const [empId, setEmpId] = useState("");
  // Employment milik user yang login (untuk sembunyikan aksi atasan atas diri sendiri)
  const [ownEmpId, setOwnEmpId] = useState("");

  // Sasaran
  const [goals, setGoals] = useState<Goal[]>([]);
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [gTitle, setGTitle] = useState("");
  const [gWeight, setGWeight] = useState(25);
  const [gTarget, setGTarget] = useState("");
  const [gDesc, setGDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [rejecting, setRejecting] = useState<Goal | null>(null);

  // Penilaian
  const [appraisal, setAppraisal] = useState<Appraisal | null>(null);
  const [selfScores, setSelfScores] = useState<Record<string, { score: number; comment: string }>>({});
  const [mgrScores, setMgrScores] = useState<Record<string, number>>({});
  const [potential, setPotential] = useState(3);

  // 9-box & rekomendasi
  const [nineBox, setNineBox] = useState<NineBox | null>(null);
  const [nineBoxError, setNineBoxError] = useState<string | null>(null);
  const [recs, setRecs] = useState<TrainingRec[]>([]);

  const loadCycle = useCallback(async () => {
    const c = await apiFetch<Cycle>(`/performance/cycles/${cycleId}`);
    setCycle(c);
  }, [cycleId]);

  const loadPeople = useCallback(async () => {
    const [emps, persons, me] = await Promise.all([
      apiFetch<Employment[]>("/employments"),
      apiFetch<Person[]>("/persons"),
      apiFetch<{ person_id: string | null }>("/me"),
    ]);
    const pm = new Map(persons.map((p) => [p.id, p.full_name]));
    // Hanya tampilkan employment yang orangnya terlihat oleh user
    // (menghindari label ID mentah + pilihan yang berujung "akses ditolak").
    const visible = emps.filter(
      (e) => e.status === "active" && pm.has(e.person_id)
    );
    setEmployments(visible);
    setPersonMap(pm);
    const own = visible.find((e) => e.person_id === me.person_id);
    setOwnEmpId(own?.id ?? "");
    if (visible.length > 0) setEmpId((prev) => prev || visible[0].id);
  }, []);

  const loadGoals = useCallback(async () => {
    if (!empId) return;
    const data = await apiFetch<Goal[]>(
      `/performance/cycles/${cycleId}/goals?employment_id=${empId}`
    );
    setGoals(data);
  }, [cycleId, empId]);

  const loadAppraisal = useCallback(async () => {
    if (!empId) {
      setAppraisal(null);
      return;
    }
    try {
      const data = await apiFetch<Appraisal[]>(
        `/performance/appraisals?employment_id=${empId}&cycle_id=${cycleId}`
      );
      setAppraisal(data[0] ?? null);
    } catch {
      setAppraisal(null);
    }
  }, [cycleId, empId]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await loadCycle();
      await loadPeople();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data.");
    } finally {
      setLoading(false);
    }
  }, [loadCycle, loadPeople]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (empId) {
      loadGoals().catch((err) =>
        setError(err instanceof ApiError ? err.message : "Gagal memuat sasaran.")
      );
      loadAppraisal();
    }
  }, [empId, loadGoals, loadAppraisal]);

  const loadNineBox = useCallback(async () => {
    setNineBoxError(null);
    try {
      const data = await apiFetch<NineBox>(
        `/performance/cycles/${cycleId}/nine-box`
      );
      setNineBox(data);
    } catch (err) {
      setNineBoxError(
        err instanceof ApiError
          ? err.message
          : "Matriks 9-box hanya dapat diakses setelah tahap kalibrasi oleh HR."
      );
    }
  }, [cycleId]);

  const loadRecs = useCallback(async () => {
    // Backend mengembalikan SATU objek rekomendasi untuk employment_id
    // yang dipilih (422 bila employment_id hilang / belum dikalibrasi).
    if (!empId) {
      setRecs([]);
      return;
    }
    try {
      const data = await apiFetch<TrainingRec>(
        `/performance/cycles/${cycleId}/training-recommendations?employment_id=${empId}`
      );
      setRecs([data]);
    } catch {
      setRecs([]);
    }
  }, [cycleId, empId]);

  useEffect(() => {
    if (tab === "ninebox" && !nineBox) loadNineBox();
    if (tab === "pelatihan") loadRecs();
  }, [tab, nineBox, loadNineBox, loadRecs]);

  const totalWeight = goals.reduce((s, g) => s + g.weight, 0);
  const empName = (id: string) => {
    const e = employments.find((x) => x.id === id);
    return e ? (personMap.get(e.person_id) ?? "—") : "—";
  };

  async function refreshGoals() {
    await loadGoals();
  }

  // ---------------------------------------------------------------- aksi sasaran
  async function createGoal(e: React.FormEvent) {
    e.preventDefault();
    if (!gTitle.trim()) {
      setActionMsg("Judul sasaran wajib diisi.");
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      await apiFetch(`/performance/cycles/${cycleId}/goals`, {
        method: "POST",
        body: JSON.stringify({
          employment_id: empId,
          title: gTitle.trim(),
          description: gDesc.trim() || null,
          weight: gWeight,
          target_text: gTarget.trim() || null,
        }),
      });
      setShowGoalForm(false);
      setGTitle("");
      setGWeight(25);
      setGTarget("");
      setGDesc("");
      await refreshGoals();
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Gagal menambah sasaran.");
    } finally {
      setBusy(false);
    }
  }

  async function goalAction(
    goal: Goal,
    action: "submit" | "approve" | "reject",
    note?: string
  ) {
    setBusy(true);
    setActionMsg(null);
    try {
      await apiFetch(`/performance/goals/${goal.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note: note || null }),
      });
      setRejecting(null);
      setRejectNote("");
      await refreshGoals();
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusy(false);
    }
  }

  // ---------------------------------------------------------------- aksi penilaian
  async function createAppraisal() {
    setBusy(true);
    setActionMsg(null);
    try {
      const data = await apiFetch<Appraisal>("/performance/appraisals", {
        method: "POST",
        body: JSON.stringify({ employment_id: empId, cycle_id: cycleId }),
      });
      setAppraisal(data);
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Gagal membuat penilaian.");
    } finally {
      setBusy(false);
    }
  }

  async function submitSelf() {
    if (!appraisal) return;
    // Backend mewajibkan skor mencakup TEPAT seluruh goal yang disetujui;
    // goal yang tak disentuh memakai default 3 (sesuai pilihan awal UI).
    const approvedGoals = goals.filter((g) => g.status === "approved");
    const scores = approvedGoals.map((g) => ({
      goal_id: g.id,
      score: selfScores[g.id]?.score ?? 3,
      comment: selfScores[g.id]?.comment || null,
    }));
    if (scores.length === 0) {
      setActionMsg("Belum ada sasaran yang disetujui.");
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      const data = await apiFetch<Appraisal>(
        `/performance/appraisals/${appraisal.id}/self-assessment`,
        { method: "POST", body: JSON.stringify({ scores }) }
      );
      setAppraisal(data);
      setActionMsg("Penilaian diri tersimpan.");
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Gagal menyimpan.");
    } finally {
      setBusy(false);
    }
  }

  async function submitManager() {
    if (!appraisal) return;
    const approvedGoals = goals.filter((g) => g.status === "approved");
    const scores = approvedGoals.map((g) => ({
      goal_id: g.id,
      score: mgrScores[g.id] ?? 3,
    }));
    if (scores.length === 0) {
      setActionMsg("Belum ada sasaran yang disetujui.");
      return;
    }
    setBusy(true);
    setActionMsg(null);
    try {
      const data = await apiFetch<Appraisal>(
        `/performance/appraisals/${appraisal.id}/manager-score`,
        { method: "POST", body: JSON.stringify({ scores }) }
      );
      setAppraisal(data);
      setActionMsg("Skor manajer tersimpan. Skor akhir dihitung otomatis.");
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Gagal menyimpan.");
    } finally {
      setBusy(false);
    }
  }

  async function submitCalibrate() {
    if (!appraisal) return;
    setBusy(true);
    setActionMsg(null);
    try {
      const data = await apiFetch<Appraisal>(
        `/performance/appraisals/${appraisal.id}/calibrate`,
        {
          method: "POST",
          body: JSON.stringify({ potential_score: potential }),
        }
      );
      setAppraisal(data);
      setNineBox(null); // segarkan matriks
      setActionMsg("Kalibrasi tersimpan.");
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : "Gagal kalibrasi.");
    } finally {
      setBusy(false);
    }
  }

  // ---------------------------------------------------------------- render
  if (loading) return <p className="text-sm text-slate-500">Memuat…</p>;
  if (error && !cycle)
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</div>
    );

  const tabs: { id: Tab; label: string }[] = [
    { id: "sasaran", label: "Sasaran" },
    { id: "penilaian", label: "Penilaian" },
    { id: "ninebox", label: "Matriks 9-Box" },
    { id: "pelatihan", label: "Rekomendasi Pelatihan" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <Link href="/penilaian" className="text-sm text-blue-600 hover:underline">
          ← Kembali ke daftar siklus
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">
            {cycle?.name ?? "Siklus"}
          </h1>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
            {cycle ? (STATUS_LABEL[cycle.status] ?? cycle.status) : ""}
          </span>
        </div>
        {cycle && (
          <p className="mt-1 text-sm text-slate-500">
            {cycle.year} · {cycle.start_date} s.d. {cycle.end_date}
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
      {actionMsg && (
        <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
          {actionMsg}
        </div>
      )}

      <div className="flex gap-1 border-b">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-blue-600 text-blue-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "sasaran" && (
        <SasaranTab
          employments={employments}
          personMap={personMap}
          empId={empId}
          setEmpId={setEmpId}
          goals={goals}
          totalWeight={totalWeight}
          busy={busy}
          isOwn={!!ownEmpId && empId === ownEmpId}
          onAdd={() => setShowGoalForm(true)}
          onAction={goalAction}
          onReject={(g) => setRejecting(g)}
        />
      )}

      {tab === "penilaian" && (
        <PenilaianTab
          employments={employments}
          personMap={personMap}
          empId={empId}
          setEmpId={setEmpId}
          goals={goals.filter((g) => g.status === "approved")}
          appraisal={appraisal}
          busy={busy}
          isOwn={!!ownEmpId && empId === ownEmpId}
          selfScores={selfScores}
          setSelfScores={setSelfScores}
          mgrScores={mgrScores}
          setMgrScores={setMgrScores}
          potential={potential}
          setPotential={setPotential}
          onCreate={createAppraisal}
          onSubmitSelf={submitSelf}
          onSubmitManager={submitManager}
          onCalibrate={submitCalibrate}
        />
      )}

      {tab === "ninebox" && (
        <div className="space-y-4">
          {nineBoxError ? (
            <EmptyState message={nineBoxError} />
          ) : !nineBox ? (
            <p className="text-sm text-slate-500">Memuat matriks…</p>
          ) : (
            <>
              <p className="text-sm text-slate-500">
                Sumbu horizontal: kinerja (skor akhir). Sumbu vertikal: potensi
                (hasil kalibrasi).
              </p>
              <div className="grid grid-cols-3 gap-2">
                {GRID.map((row, ri) =>
                  row.map((cell, ci) => {
                    const entries = nineBox.boxes[cell.key] ?? [];
                    const label =
                      entries[0]?.label_id ??
                      {
                        star: "Bintang",
                        high_performer: "Berkinerja Tinggi",
                        trusted_professional: "Profesional Andal",
                        high_potential: "Potensi Tinggi",
                        key_player: "Pemain Kunci",
                        average_performer: "Kinerja Rata-rata",
                        rough_diamond: "Berlian Mentah",
                        inconsistent_player: "Kinerja Tidak Konsisten",
                        low_performer: "Kinerja Rendah",
                      }[cell.key];
                    return (
                      <div
                        key={`${ri}-${ci}`}
                        className={`min-h-28 rounded-xl border p-3 ${BOX_COLOR[cell.key]}`}
                      >
                        <p className="text-xs font-semibold text-slate-700">
                          {label}
                        </p>
                        <p className="text-[10px] text-slate-500">
                          Kinerja {cell.perf} · Potensi {cell.pot}
                        </p>
                        <ul className="mt-2 space-y-1">
                          {entries.map((e) => (
                            <li
                              key={e.employment_id}
                              className="text-xs text-slate-800"
                            >
                              {e.person_name}{" "}
                              <span className="text-slate-500">
                                ({e.final_score.toFixed(2)}/{e.potential_score})
                              </span>
                            </li>
                          ))}
                        </ul>
                        {entries.length === 0 && (
                          <p className="mt-2 text-[11px] italic text-slate-400">
                            Kosong
                          </p>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </>
          )}
        </div>
      )}

      {tab === "pelatihan" && (
        <div className="space-y-4">
          {recs.length === 0 ? (
            <EmptyState message="Belum ada rekomendasi. Rekomendasi muncul setelah kalibrasi." />
          ) : (
            recs.map((r) => (
              <div
                key={r.employment_id}
                className="rounded-xl bg-white p-4 shadow"
              >
                <p className="font-medium text-slate-900">
                  {r.person_name}{" "}
                  <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {r.label_id}
                  </span>
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Skor akhir {r.final_score.toFixed(2)} · Potensi {r.potential_score}
                </p>
                <p className="mt-2 text-sm text-slate-700">
                  Kategori disarankan: {r.recommended_categories.join(", ")}
                </p>
                {r.courses.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-sm text-slate-600">
                    {r.courses.map((c) => (
                      <li key={c.id}>
                        {c.code} — {c.name}
                        {c.provider ? ` (${c.provider})` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {showGoalForm && (
        <Modal
          title="Tambah sasaran"
          onClose={() => !busy && setShowGoalForm(false)}
          actions={
            <>
              <button
                onClick={() => setShowGoalForm(false)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={createGoal}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Simpan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Judul sasaran
              </label>
              <input
                value={gTitle}
                onChange={(e) => setGTitle(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="cth. Menyelesaikan migrasi modul payroll"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Bobot (%) — total semua sasaran wajib 100
              </label>
              <input
                type="number"
                min={1}
                max={100}
                value={gWeight}
                onChange={(e) => setGWeight(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Target
              </label>
              <input
                value={gTarget}
                onChange={(e) => setGTarget(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="cth. 100% tepat waktu"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Deskripsi
              </label>
              <textarea
                value={gDesc}
                onChange={(e) => setGDesc(e.target.value)}
                rows={3}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
        </Modal>
      )}

      {rejecting && (
        <Modal
          title="Tolak sasaran"
          onClose={() => !busy && setRejecting(null)}
          actions={
            <>
              <button
                onClick={() => setRejecting(null)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={() => goalAction(rejecting, "reject", rejectNote)}
                disabled={busy}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {busy ? "Memproses…" : "Tolak sasaran"}
              </button>
            </>
          }
        >
          <p>
            Tolak sasaran <strong>{rejecting.title}</strong>?
          </p>
          <label className="mb-1 mt-3 block text-xs font-medium text-slate-700">
            Catatan untuk karyawan
          </label>
          <textarea
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Alasan penolakan…"
          />
        </Modal>
      )}
    </div>
  );
}

// ================================================================ sub-komponen
// Didefinisikan di file yang sama agar satu halaman tetap kohesif.

function EmpSelect({
  employments,
  personMap,
  empId,
  setEmpId,
}: {
  employments: { id: string; person_id: string; status: string }[];
  personMap: Map<string, string>;
  empId: string;
  setEmpId: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-700">
        Karyawan
      </label>
      <select
        value={empId}
        onChange={(e) => setEmpId(e.target.value)}
        className="w-full max-w-sm rounded-lg border border-slate-300 px-3 py-2 text-sm"
      >
        {employments.map((e) => (
          <option key={e.id} value={e.id}>
            {personMap.get(e.person_id) ?? "—"}
          </option>
        ))}
      </select>
    </div>
  );
}

function SasaranTab({
  employments,
  personMap,
  empId,
  setEmpId,
  goals,
  totalWeight,
  busy,
  isOwn,
  onAdd,
  onAction,
  onReject,
}: {
  employments: { id: string; person_id: string; status: string }[];
  personMap: Map<string, string>;
  empId: string;
  setEmpId: (v: string) => void;
  goals: Goal[];
  totalWeight: number;
  busy: boolean;
  isOwn: boolean;
  onAdd: () => void;
  onAction: (
    goal: Goal,
    action: "submit" | "approve" | "reject",
    note?: string
  ) => void;
  onReject: (goal: Goal) => void;
}) {
  const GOAL_STATUS_LABEL: Record<string, string> = {
    draft: "Draf",
    submitted: "Diajukan",
    approved: "Disetujui",
    rejected: "Ditolak",
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <EmpSelect
          employments={employments}
          personMap={personMap}
          empId={empId}
          setEmpId={setEmpId}
        />
        <button
          onClick={onAdd}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + Tambah sasaran
        </button>
      </div>

      <div
        className={`rounded-lg p-3 text-sm ${
          totalWeight === 100
            ? "bg-emerald-50 text-emerald-800"
            : "bg-amber-50 text-amber-800"
        }`}
      >
        Total bobot: <strong>{totalWeight}%</strong>
        {totalWeight !== 100 &&
          " — total wajib 100% sebelum sasaran bisa diajukan."}
      </div>

      {goals.length === 0 ? (
        <EmptyState message="Belum ada sasaran untuk karyawan ini pada siklus ini." />
      ) : (
        <div className="space-y-3">
          {goals.map((g) => (
            <div key={g.id} className="rounded-xl bg-white p-4 shadow">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-slate-900">{g.title}</p>
                  {g.target_text && (
                    <p className="mt-0.5 text-xs text-slate-500">
                      Target: {g.target_text}
                    </p>
                  )}
                  {g.manager_comment && (
                    <p className="mt-0.5 text-xs italic text-slate-500">
                      Catatan atasan: {g.manager_comment}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    Bobot {g.weight}%
                  </span>
                  <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                    {GOAL_STATUS_LABEL[g.status] ?? g.status}
                  </span>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {g.status === "draft" && (
                  <button
                    onClick={() => onAction(g, "submit")}
                    disabled={busy || totalWeight !== 100}
                    title={
                      totalWeight !== 100
                        ? "Total bobot harus 100%"
                        : "Ajukan ke atasan"
                    }
                    className="rounded-lg border border-blue-600 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-40"
                  >
                    Ajukan
                  </button>
                )}
                {g.status === "submitted" && !isOwn && (
                  <>
                    <button
                      onClick={() => onAction(g, "approve")}
                      disabled={busy}
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      Setujui
                    </button>
                    <button
                      onClick={() => onReject(g)}
                      disabled={busy}
                      className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      Tolak
                    </button>
                  </>
                )}
                {g.status === "submitted" && isOwn && (
                  <span className="text-xs italic text-slate-500">
                    Menunggu persetujuan atasan.
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PenilaianTab({
  employments,
  personMap,
  empId,
  setEmpId,
  goals,
  appraisal,
  busy,
  isOwn,
  selfScores,
  setSelfScores,
  mgrScores,
  setMgrScores,
  potential,
  setPotential,
  onCreate,
  onSubmitSelf,
  onSubmitManager,
  onCalibrate,
}: {
  employments: { id: string; person_id: string; status: string }[];
  personMap: Map<string, string>;
  empId: string;
  setEmpId: (v: string) => void;
  goals: { id: string; title: string; weight: number }[];
  appraisal: {
    id: string;
    self_scores:
      | { goal_id: string; score: number; comment?: string }[]
      | null;
    self_submitted_at: string | null;
    manager_scores: { goal_id: string; score: number }[] | null;
    manager_submitted_at: string | null;
    potential_score: number | null;
    final_score: number | null;
  } | null;
  busy: boolean;
  isOwn: boolean;
  selfScores: Record<string, { score: number; comment: string }>;
  setSelfScores: (
    v: Record<string, { score: number; comment: string }>
  ) => void;
  mgrScores: Record<string, number>;
  setMgrScores: (v: Record<string, number>) => void;
  potential: number;
  setPotential: (v: number) => void;
  onCreate: () => void;
  onSubmitSelf: () => void;
  onSubmitManager: () => void;
  onCalibrate: () => void;
}) {
  const goalTitle = (id: string) =>
    goals.find((g) => g.id === id)?.title ?? id.slice(0, 8);

  return (
    <div className="space-y-4">
      <EmpSelect
        employments={employments}
        personMap={personMap}
        empId={empId}
        setEmpId={setEmpId}
      />

      {!appraisal ? (
        <div className="rounded-xl bg-white p-6 text-center shadow">
          <p className="text-sm text-slate-600">
            Belum ada penilaian untuk karyawan ini pada siklus ini.
          </p>
          <button
            onClick={onCreate}
            disabled={busy}
            className="mt-3 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? "Memproses…" : "Buat penilaian"}
          </button>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-white p-4 shadow">
              <p className="text-xs text-slate-500">Penilaian diri</p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {appraisal.self_submitted_at ? "Sudah diisi" : "Belum diisi"}
              </p>
            </div>
            <div className="rounded-xl bg-white p-4 shadow">
              <p className="text-xs text-slate-500">Skor manajer</p>
              <p className="mt-1 text-sm font-medium text-slate-900">
                {appraisal.manager_submitted_at ? "Sudah diisi" : "Belum diisi"}
              </p>
            </div>
            <div className="rounded-xl bg-white p-4 shadow">
              <p className="text-xs text-slate-500">Skor akhir</p>
              <p className="mt-1 text-lg font-bold text-slate-900">
                {appraisal.final_score != null
                  ? Number(appraisal.final_score).toFixed(2)
                  : "—"}
                {appraisal.potential_score != null && (
                  <span className="ml-2 text-xs font-normal text-slate-500">
                    Potensi {appraisal.potential_score}/5
                  </span>
                )}
              </p>
            </div>
          </div>

          {goals.length === 0 && (
            <EmptyState message="Belum ada sasaran yang disetujui — penilaian membutuhkan sasaran yang sudah disetujui atasan." />
          )}

          {goals.length > 0 && (
            <>
              <div className="rounded-xl bg-white p-4 shadow">
                <h3 className="font-medium text-slate-900">
                  Penilaian diri (karyawan)
                </h3>
                <p className="mb-3 text-xs text-slate-500">
                  Beri skor 1–5 untuk tiap sasaran yang disetujui.
                </p>
                <div className="space-y-3">
                  {goals.map((g) => (
                    <div key={g.id} className="border-b pb-3 last:border-0">
                      <p className="text-sm font-medium text-slate-800">
                        {g.title}{" "}
                        <span className="text-xs text-slate-400">
                          (bobot {g.weight}%)
                        </span>
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <select
                          value={selfScores[g.id]?.score ?? 3}
                          onChange={(e) =>
                            setSelfScores({
                              ...selfScores,
                              [g.id]: {
                                score: Number(e.target.value),
                                comment: selfScores[g.id]?.comment ?? "",
                              },
                            })
                          }
                          className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                        >
                          {[1, 2, 3, 4, 5].map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                        <input
                          value={selfScores[g.id]?.comment ?? ""}
                          onChange={(e) =>
                            setSelfScores({
                              ...selfScores,
                              [g.id]: {
                                score: selfScores[g.id]?.score ?? 3,
                                comment: e.target.value,
                              },
                            })
                          }
                          placeholder="Komentar (opsional)"
                          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <button
                  onClick={onSubmitSelf}
                  disabled={busy}
                  className="mt-3 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {busy ? "Menyimpan…" : "Simpan penilaian diri"}
                </button>
              </div>

              {!isOwn && (
                <div className="rounded-xl bg-white p-4 shadow">
                  <h3 className="font-medium text-slate-900">
                    Skor manajer (atasan)
                  </h3>
                <p className="mb-3 text-xs text-slate-500">
                  Skor akhir = Σ (bobot × skor manajer) ÷ 100.
                </p>
                <div className="space-y-3">
                  {goals.map((g) => (
                    <div
                      key={g.id}
                      className="flex items-center justify-between gap-3 border-b pb-3 last:border-0"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {g.title}{" "}
                        <span className="text-xs text-slate-400">
                          (bobot {g.weight}%)
                        </span>
                      </p>
                      <select
                        value={mgrScores[g.id] ?? 3}
                        onChange={(e) =>
                          setMgrScores({
                            ...mgrScores,
                            [g.id]: Number(e.target.value),
                          })
                        }
                        className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                      >
                        {[1, 2, 3, 4, 5].map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
                <button
                  onClick={onSubmitManager}
                  disabled={busy}
                  className="mt-3 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {busy ? "Menyimpan…" : "Simpan skor manajer"}
                </button>
                </div>
              )}

              {!isOwn && (
                <div className="rounded-xl bg-white p-4 shadow">
                  <h3 className="font-medium text-slate-900">
                    Kalibrasi potensi (HR)
                  </h3>
                <p className="mb-3 text-xs text-slate-500">
                  Skor potensi 1–5 menentukan posisi vertikal di matriks 9-box.
                </p>
                <div className="flex items-center gap-3">
                  <select
                    value={potential}
                    onChange={(e) => setPotential(Number(e.target.value))}
                    className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                  >
                    {[1, 2, 3, 4, 5].map((s) => (
                      <option key={s} value={s}>
                        {s} —{" "}
                        {["Sangat rendah", "Rendah", "Sedang", "Tinggi", "Sangat tinggi"][s - 1]}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={onCalibrate}
                    disabled={busy}
                    className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
                  >
                    {busy ? "Menyimpan…" : "Simpan kalibrasi"}
                  </button>
                  </div>
                </div>
              )}

              {(appraisal.self_scores?.length ?? 0) > 0 && (
                <details className="rounded-xl bg-white p-4 shadow">
                  <summary className="cursor-pointer text-sm font-medium text-slate-700">
                    Riwayat skor tersimpan
                  </summary>
                  <div className="mt-2 space-y-1 text-xs text-slate-600">
                    {(appraisal.self_scores ?? []).map((s) => (
                      <p key={s.goal_id}>
                        Diri — {goalTitle(s.goal_id)}: {s.score}
                        {s.comment ? ` (“${s.comment}”)` : ""}
                      </p>
                    ))}
                    {(appraisal.manager_scores ?? []).map((s) => (
                      <p key={s.goal_id}>
                        Manajer — {goalTitle(s.goal_id)}: {s.score}
                      </p>
                    ))}
                  </div>
                </details>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
