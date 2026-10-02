"use client";

import { useCallback, useEffect, useState } from "react";
import { apiDownload, apiFetch, ApiError } from "@/lib/api";
import type {
  CompBudget,
  CompCycle,
  CompCycleDetail,
  CompEmployee,
  CompProposal,
  JobGrade,
  Me,
  PayEquity,
  PayGrade,
  TotalRewards,
} from "@/lib/types";
import { rupiah, tanggal } from "@/lib/format";
import {
  btnDanger,
  btnPrimary,
  btnSecondary,
  btnSmall,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  inputCls,
  Modal,
  PageHeader,
  Spinner,
} from "@/components/ui";

type TabId = "grade" | "karyawan" | "siklus" | "analitik";

const CYCLE_STATUS: Record<string, string> = {
  draft: "Draft",
  open: "Dibuka",
  finalized: "Selesai",
  cancelled: "Dibatalkan",
};

const PROPOSAL_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "Draft", cls: "bg-slate-100 text-slate-700" },
  submitted: { label: "Diajukan", cls: "bg-blue-100 text-blue-700" },
  pending_extra_approval: {
    label: "Menunggu Persetujuan Tambahan",
    cls: "bg-amber-100 text-amber-800",
  },
  approved: { label: "Disetujui", cls: "bg-green-100 text-green-700" },
  rejected: { label: "Ditolak", cls: "bg-red-100 text-red-700" },
};

function compaChip(ratio: number | null) {
  if (ratio === null) return <span className="text-slate-400">—</span>;
  const pct = `${(ratio * 100).toFixed(0)}%`;
  if (ratio < 0.8)
    return (
      <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
        {pct} · di bawah band
      </span>
    );
  if (ratio <= 1.0)
    return (
      <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
        {pct} · dalam band
      </span>
    );
  return (
    <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
      {pct} · di atas band
    </span>
  );
}

export default function KompensasiPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<TabId>("grade");
  const [grades, setGrades] = useState<PayGrade[]>([]);
  const [jobs, setJobs] = useState<JobGrade[]>([]);
  const [employees, setEmployees] = useState<CompEmployee[]>([]);
  const [cycles, setCycles] = useState<CompCycle[]>([]);
  const [detail, setDetail] = useState<CompCycleDetail | null>(null);
  const [equity, setEquity] = useState<PayEquity | null>(null);
  const [myRewards, setMyRewards] = useState<TotalRewards | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isHr = Boolean(me?.is_hr || me?.is_superadmin);
  const canPropose = isHr || Boolean(me?.roles?.includes("Manajer"));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [meData, g, j, e, c] = await Promise.all([
        apiFetch<Me>("/me"),
        apiFetch<PayGrade[]>("/compensation/pay-grades"),
        apiFetch<JobGrade[]>("/compensation/jobs"),
        apiFetch<CompEmployee[]>("/compensation/employees"),
        apiFetch<CompCycle[]>("/compensation/cycles"),
      ]);
      setMe(meData);
      setGrades(g);
      setJobs(j);
      setEmployees(e);
      setCycles(c);
      try {
        setMyRewards(await apiFetch<TotalRewards>("/compensation/total-rewards/me"));
      } catch {
        setMyRewards(null);
      }
      try {
        setEquity(await apiFetch<PayEquity>("/compensation/analytics/pay-equity"));
      } catch {
        setEquity(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat kompensasi.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function openCycle(id: string) {
    setActionError(null);
    try {
      setDetail(await apiFetch<CompCycleDetail>(`/compensation/cycles/${id}`));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal membuka siklus.");
    }
  }

  async function refreshDetail(id: string) {
    setDetail(await apiFetch<CompCycleDetail>(`/compensation/cycles/${id}`));
    setCycles(await apiFetch<CompCycle[]>("/compensation/cycles"));
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  const tabs: { id: TabId; label: string }[] = [
    { id: "grade", label: "Grade & Band" },
    { id: "karyawan", label: "Karyawan & Compa-Ratio" },
    { id: "siklus", label: `Siklus Merit${cycles.length ? ` (${cycles.length})` : ""}` },
    { id: "analitik", label: "Analitik Kesetaraan" },
  ];

  return (
    <div>
      <PageHeader
        title="Kompensasi"
        subtitle="Pay grade, compa-ratio, siklus merit/bonus, dan total rewards"
        action={
          <button
            className={btnSecondary}
            onClick={() =>
              apiDownload("/compensation/total-rewards/me/pdf", "total-rewards-saya.pdf")
            }
          >
            Unduh Total Rewards Saya (PDF)
          </button>
        }
      />

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {myRewards && (
        <Card className="mb-4">
          <p className="text-sm text-slate-600">
            Total rewards tahunan Anda:{" "}
            <span className="font-semibold text-slate-900">
              {rupiah(myRewards.annual_total)}
            </span>{" "}
            (tunai bulanan {rupiah(myRewards.monthly_cash)} + kontribusi
            perusahaan {rupiah(myRewards.employer_bpjs_total_monthly)}/bulan +
            THR {rupiah(myRewards.thr_estimate)})
          </p>
        </Card>
      )}

      <div className="mb-4 flex gap-2 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "grade" && (
        <GradeTab
          grades={grades}
          jobs={jobs}
          isHr={isHr}
          busy={busy}
          setBusy={setBusy}
          onChanged={load}
          setActionError={setActionError}
        />
      )}
      {tab === "karyawan" && (
        <KaryawanTab employees={employees} isHr={isHr} />
      )}
      {tab === "siklus" && (
        <SiklusTab
          cycles={cycles}
          detail={detail}
          employees={employees}
          isHr={isHr}
          canPropose={canPropose}
          busy={busy}
          setBusy={setBusy}
          onOpen={openCycle}
          onChanged={async () => {
            await load();
            if (detail) await refreshDetail(detail.cycle.id);
          }}
          refreshDetail={refreshDetail}
          setActionError={setActionError}
        />
      )}
      {tab === "analitik" && <AnalitikTab equity={equity} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab Grade & Band
// ---------------------------------------------------------------------------

function GradeTab({
  grades,
  jobs,
  isHr,
  busy,
  setBusy,
  onChanged,
  setActionError,
}: {
  grades: PayGrade[];
  jobs: JobGrade[];
  isHr: boolean;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onChanged: () => Promise<void>;
  setActionError: (m: string | null) => void;
}) {
  const [form, setForm] = useState({ code: "", name: "", band_min: "", band_mid: "", band_max: "" });

  async function createGrade(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      await apiFetch("/compensation/pay-grades", {
        method: "POST",
        body: JSON.stringify({
          code: form.code,
          name: form.name,
          band_min: Number(form.band_min),
          band_mid: Number(form.band_mid),
          band_max: Number(form.band_max),
        }),
      });
      setForm({ code: "", name: "", band_min: "", band_mid: "", band_max: "" });
      await onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal membuat pay grade.");
    } finally {
      setBusy(false);
    }
  }

  async function assignGrade(jobId: string, gradeId: string) {
    setActionError(null);
    try {
      await apiFetch("/compensation/job-grades", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, pay_grade_id: gradeId || null }),
      });
      await onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menetapkan grade jabatan.");
    }
  }

  return (
    <div className="space-y-4">
      {isHr && (
        <Card>
          <h3 className="mb-3 font-semibold text-slate-900">Buat Pay Grade</h3>
          <form onSubmit={createGrade} className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Field label="Kode">
              <input className={inputCls} value={form.code} required
                onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="G5" />
            </Field>
            <Field label="Nama">
              <input className={inputCls} value={form.name} required
                onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Senior Staff" />
            </Field>
            <Field label="Band minimum (Rp)">
              <input className={inputCls} type="number" min={0} value={form.band_min} required
                onChange={(e) => setForm({ ...form, band_min: e.target.value })} />
            </Field>
            <Field label="Band tengah (Rp)">
              <input className={inputCls} type="number" min={0} value={form.band_mid} required
                onChange={(e) => setForm({ ...form, band_mid: e.target.value })} />
            </Field>
            <Field label="Band maksimum (Rp)">
              <input className={inputCls} type="number" min={0} value={form.band_max} required
                onChange={(e) => setForm({ ...form, band_max: e.target.value })} />
            </Field>
            <div className="flex items-end">
              <button className={btnPrimary} disabled={busy} type="submit">Simpan</button>
            </div>
          </form>
        </Card>
      )}

      <Card>
        <h3 className="mb-3 font-semibold text-slate-900">Daftar Pay Grade</h3>
        {grades.length === 0 ? (
          <EmptyState message="Belum ada pay grade." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">Kode</th><th>Nama</th><th>Minimum</th>
                <th>Tengah</th><th>Maksimum</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {grades.map((g) => (
                <tr key={g.id} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{g.code}</td>
                  <td>{g.name}</td>
                  <td>{rupiah(g.band_min)}</td>
                  <td>{rupiah(g.band_mid)}</td>
                  <td>{rupiah(g.band_max)}</td>
                  <td>{g.is_active ? "Aktif" : "Nonaktif"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card>
        <h3 className="mb-3 font-semibold text-slate-900">Grade per Jabatan</h3>
        {jobs.length === 0 ? (
          <EmptyState message="Belum ada jabatan." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">Kode</th><th>Jabatan</th><th>Pay Grade</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{j.code}</td>
                  <td>{j.title}</td>
                  <td>
                    {isHr ? (
                      <select
                        className={`${inputCls} max-w-xs`}
                        value={j.pay_grade_id ?? ""}
                        onChange={(e) => assignGrade(j.job_id, e.target.value)}
                      >
                        <option value="">— Belum ditetapkan —</option>
                        {grades.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.code} — {g.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      j.grade_code ?? "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab Karyawan & Compa-Ratio
// ---------------------------------------------------------------------------

function KaryawanTab({ employees, isHr }: { employees: CompEmployee[]; isHr: boolean }) {
  return (
    <Card>
      {employees.length === 0 ? (
        <EmptyState message="Tidak ada data karyawan dalam cakupan Anda." />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="py-2">Karyawan</th><th>Unit</th><th>Jabatan</th>
              <th>Grade</th><th>Gaji Pokok</th><th>Compa-Ratio</th>
              {isHr && <th>Total Rewards</th>}
            </tr>
          </thead>
          <tbody>
            {employees.map((e) => (
              <tr key={e.employment_id} className="border-t border-slate-100">
                <td className="py-2 font-medium">{e.person_name}</td>
                <td>{e.org_unit_name ?? "—"}</td>
                <td>{e.job_title ?? "—"}</td>
                <td>{e.grade_code ?? "—"}</td>
                <td>{e.gaji_pokok !== null ? rupiah(e.gaji_pokok) : "—"}</td>
                <td>{compaChip(e.compa_ratio)}</td>
                {isHr && (
                  <td>
                    <button
                      className={btnSmall}
                      onClick={() =>
                        apiDownload(
                          `/compensation/employees/${e.employment_id}/total-rewards/pdf`,
                          `total-rewards-${(e.person_name ?? "karyawan").replaceAll(" ", "-").toLowerCase()}.pdf`
                        )
                      }
                    >
                      Unduh PDF
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tab Siklus Merit/Bonus
// ---------------------------------------------------------------------------

function SiklusTab({
  cycles,
  detail,
  employees,
  isHr,
  canPropose,
  busy,
  setBusy,
  onOpen,
  onChanged,
  refreshDetail,
  setActionError,
}: {
  cycles: CompCycle[];
  detail: CompCycleDetail | null;
  employees: CompEmployee[];
  isHr: boolean;
  canPropose: boolean;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onOpen: (id: string) => Promise<void>;
  onChanged: () => Promise<void>;
  refreshDetail: (id: string) => Promise<void>;
  setActionError: (m: string | null) => void;
}) {
  const [form, setForm] = useState({
    name: "", kind: "merit", period_year: String(new Date().getFullYear() + 1),
    effective_date: `${new Date().getFullYear() + 1}-01-01`,
  });
  const [proposalForm, setProposalForm] = useState({ employment_id: "", proposed_salary: "", notes: "" });
  const [budgetInputs, setBudgetInputs] = useState<Record<string, string>>({});
  const [confirmFinalize, setConfirmFinalize] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusy(false);
    }
  }

  async function createCycle(e: React.FormEvent) {
    e.preventDefault();
    await run(async () => {
      await apiFetch("/compensation/cycles", {
        method: "POST",
        body: JSON.stringify({
          name: form.name, kind: form.kind,
          period_year: Number(form.period_year),
          effective_date: form.effective_date,
        }),
      });
      setForm({ ...form, name: "" });
      await onChanged();
    });
  }

  async function cycleAction(id: string, action: string) {
    await run(async () => {
      await apiFetch(`/compensation/cycles/${id}/${action}`, { method: "POST" });
      await onChanged();
      if (detail?.cycle.id === id) await refreshDetail(id);
    });
  }

  async function proposalAction(id: string, action: string) {
    if (!detail) return;
    await run(async () => {
      await apiFetch(`/compensation/proposals/${id}/${action}`, { method: "POST" });
      await refreshDetail(detail.cycle.id);
    });
  }

  async function createProposal(e: React.FormEvent) {
    e.preventDefault();
    if (!detail) return;
    await run(async () => {
      await apiFetch(`/compensation/cycles/${detail.cycle.id}/proposals`, {
        method: "POST",
        body: JSON.stringify({
          employment_id: proposalForm.employment_id,
          proposed_salary: Number(proposalForm.proposed_salary),
          notes: proposalForm.notes || null,
        }),
      });
      setProposalForm({ employment_id: "", proposed_salary: "", notes: "" });
      await refreshDetail(detail.cycle.id);
    });
  }

  async function saveBudget(b: CompBudget) {
    if (!detail) return;
    const raw = budgetInputs[b.org_unit_id];
    if (raw === undefined || raw === "") return;
    await run(async () => {
      await apiFetch(
        `/compensation/cycles/${detail.cycle.id}/budgets/${b.org_unit_id}`,
        { method: "PUT", body: JSON.stringify({ budget_amount: Number(raw) }) }
      );
      await refreshDetail(detail.cycle.id);
    });
  }

  const cycle = detail?.cycle;
  const cycleClosed = cycle ? ["finalized", "cancelled"].includes(cycle.status) : true;

  return (
    <div className="space-y-4">
      {isHr && (
        <Card>
          <h3 className="mb-3 font-semibold text-slate-900">Buat Siklus</h3>
          <form onSubmit={createCycle} className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Field label="Nama siklus">
              <input className={inputCls} value={form.name} required
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Merit 2027" />
            </Field>
            <Field label="Jenis">
              <select className={inputCls} value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                <option value="merit">Merit (kenaikan gaji)</option>
                <option value="bonus">Bonus</option>
              </select>
            </Field>
            <Field label="Tahun periode">
              <input className={inputCls} type="number" value={form.period_year} required
                onChange={(e) => setForm({ ...form, period_year: e.target.value })} />
            </Field>
            <Field label="Tanggal efektif">
              <input className={inputCls} type="date" value={form.effective_date} required
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })} />
            </Field>
            <div className="flex items-end">
              <button className={btnPrimary} disabled={busy} type="submit">Buat</button>
            </div>
          </form>
        </Card>
      )}

      <Card>
        <h3 className="mb-3 font-semibold text-slate-900">Daftar Siklus</h3>
        {cycles.length === 0 ? (
          <EmptyState message="Belum ada siklus kompensasi." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">Nama</th><th>Jenis</th><th>Periode</th>
                <th>Efektif</th><th>Status</th><th>Usulan</th><th></th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((c) => (
                <tr key={c.id} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{c.name}</td>
                  <td>{c.kind === "merit" ? "Merit" : "Bonus"}</td>
                  <td>{c.period_year}</td>
                  <td>{tanggal(c.effective_date)}</td>
                  <td>{CYCLE_STATUS[c.status] ?? c.status}</td>
                  <td>{c.proposal_approved}/{c.proposal_total} disetujui</td>
                  <td>
                    <button className={btnSmall} onClick={() => onOpen(c.id)}>
                      Buka Detail
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {cycle && detail && (
        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <h3 className="font-semibold text-slate-900">{cycle.name}</h3>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
              {CYCLE_STATUS[cycle.status] ?? cycle.status}
            </span>
            <span className="text-xs text-slate-500">
              Efektif {tanggal(cycle.effective_date)}
            </span>
            {isHr && cycle.status === "draft" && (
              <button className={btnSmall} disabled={busy}
                onClick={() => cycleAction(cycle.id, "open")}>
                Buka Siklus
              </button>
            )}
            {isHr && !cycleClosed && (
              <>
                <button className={btnSmall} disabled={busy}
                  onClick={() => setConfirmFinalize(true)}>
                  Finalisasi
                </button>
                <button className={btnDanger} disabled={busy}
                  onClick={() => cycleAction(cycle.id, "cancel")}>
                  Batalkan
                </button>
              </>
            )}
          </div>

          <h4 className="mb-2 text-sm font-semibold text-slate-800">Anggaran per Unit (tahunan)</h4>
          {detail.budgets.length === 0 ? (
            <p className="mb-4 text-sm text-slate-500">Belum ada unit dengan usulan/anggaran.</p>
          ) : (
            <table className="mb-4 w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1">Unit</th><th>Anggaran</th><th>Terpakai</th><th>Sisa</th>
                  {isHr && <th></th>}
                </tr>
              </thead>
              <tbody>
                {detail.budgets.map((b) => (
                  <tr key={b.org_unit_id} className="border-t border-slate-100">
                    <td className="py-1">{b.org_unit_name ?? "—"}</td>
                    <td>{b.budget_amount !== null ? rupiah(b.budget_amount) : "Belum ditetapkan"}</td>
                    <td>{rupiah(b.used_amount)}</td>
                    <td className={b.remaining !== null && b.remaining < 0 ? "font-semibold text-red-700" : ""}>
                      {b.remaining !== null ? rupiah(b.remaining) : "—"}
                    </td>
                    {isHr && !cycleClosed && (
                      <td>
                        <div className="flex gap-1">
                          <input
                            className={`${inputCls} max-w-[160px]`}
                            type="number" min={0} placeholder="Nominal"
                            value={budgetInputs[b.org_unit_id] ?? ""}
                            onChange={(e) =>
                              setBudgetInputs({ ...budgetInputs, [b.org_unit_id]: e.target.value })}
                          />
                          <button className={btnSmall} disabled={busy}
                            onClick={() => saveBudget(b)}>
                            Simpan
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4 className="mb-2 text-sm font-semibold text-slate-800">Usulan Karyawan</h4>
          {detail.proposals.length === 0 ? (
            <p className="mb-4 text-sm text-slate-500">Belum ada usulan pada siklus ini.</p>
          ) : (
            <table className="mb-4 w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1">Karyawan</th><th>Gaji Kini</th><th>Usulan</th>
                  <th>Kenaikan</th><th>Guideline</th><th>Status</th><th></th>
                </tr>
              </thead>
              <tbody>
                {detail.proposals.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100 align-top">
                    <td className="py-1 font-medium">
                      {p.person_name}
                      <span className="block text-xs font-normal text-slate-500">
                        {p.org_unit_name ?? ""}
                        {p.rating !== null ? ` · Rating ${p.rating}` : ""}
                      </span>
                    </td>
                    <td>{rupiah(p.current_salary)}</td>
                    <td>{rupiah(p.proposed_salary)}</td>
                    <td>+{p.increase_pct}%</td>
                    <td>
                      {p.guideline_min_pct !== null ? (
                        <span className={p.within_guideline ? "text-green-700" : "font-semibold text-amber-700"}>
                          {p.guideline_min_pct}–{p.guideline_max_pct}%
                          {p.within_guideline ? " ✓" : " (di luar)"}
                        </span>
                      ) : "—"}
                    </td>
                    <td>
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${PROPOSAL_STATUS[p.status].cls}`}>
                        {PROPOSAL_STATUS[p.status].label}
                      </span>
                      {p.over_budget && (
                        <span className="ml-1 rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                          Melebihi anggaran
                        </span>
                      )}
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {p.status === "draft" && canPropose && (
                          <button className={btnSmall} disabled={busy}
                            onClick={() => proposalAction(p.id, "submit")}>
                            Ajukan
                          </button>
                        )}
                        {p.status === "submitted" && isHr && (
                          <>
                            <button className={btnSmall} disabled={busy}
                              onClick={() => proposalAction(p.id, "approve")}>
                              Setujui
                            </button>
                            <button className={btnSmall} disabled={busy}
                              onClick={() => proposalAction(p.id, "reject")}>
                              Tolak
                            </button>
                          </>
                        )}
                        {p.status === "pending_extra_approval" && isHr && (
                          <>
                            <button className={btnSmall} disabled={busy}
                              onClick={() => proposalAction(p.id, "approve-extra")}>
                              Setujui Tambahan
                            </button>
                            <button className={btnSmall} disabled={busy}
                              onClick={() => proposalAction(p.id, "reject")}>
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
          )}

          {canPropose && !cycleClosed && (
            <form onSubmit={createProposal} className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Karyawan">
                <select className={inputCls} value={proposalForm.employment_id} required
                  onChange={(e) => setProposalForm({ ...proposalForm, employment_id: e.target.value })}>
                  <option value="">— Pilih karyawan —</option>
                  {employees.map((e) => (
                    <option key={e.employment_id} value={e.employment_id}>
                      {e.person_name} ({e.gaji_pokok !== null ? rupiah(e.gaji_pokok) : "tanpa gaji"})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={cycle.kind === "merit" ? "Gaji pokok baru (Rp)" : "Nominal bonus (Rp)"}>
                <input className={inputCls} type="number" min={0} required
                  value={proposalForm.proposed_salary}
                  onChange={(e) => setProposalForm({ ...proposalForm, proposed_salary: e.target.value })} />
              </Field>
              <Field label="Catatan">
                <input className={inputCls} value={proposalForm.notes}
                  onChange={(e) => setProposalForm({ ...proposalForm, notes: e.target.value })} />
              </Field>
              <div className="flex items-end">
                <button className={btnPrimary} disabled={busy} type="submit">Tambah Usulan</button>
              </div>
            </form>
          )}
        </Card>
      )}

      {confirmFinalize && cycle && (
        <Modal
          title="Finalisasi Siklus"
          onClose={() => setConfirmFinalize(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setConfirmFinalize(false)}>
                Kembali
              </button>
              <button
                className={btnPrimary}
                disabled={busy}
                onClick={async () => {
                  setConfirmFinalize(false);
                  await cycleAction(cycle.id, "finalize");
                }}
              >
                Ya, Finalisasi
              </button>
            </>
          }
        >
          {cycle.kind === "merit"
            ? "Seluruh usulan yang disetujui akan ditulis sebagai kompensasi baru bertanggal efektif " +
              `${tanggal(cycle.effective_date)} (alasan: Merit). Usulan yang belum diputuskan akan menggagalkan finalisasi. Lanjutkan?`
            : "Siklus bonus akan ditutup. Nominal bonus dibayarkan melalui proses payroll terpisah. Lanjutkan?"}
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab Analitik Kesetaraan
// ---------------------------------------------------------------------------

function AnalitikTab({ equity }: { equity: PayEquity | null }) {
  if (!equity) {
    return (
      <Card>
        <EmptyState message="Analitik kesetaraan hanya tampil untuk peran dengan izin khusus (HR)." />
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 font-semibold text-slate-900">Rata-rata Gaji Pokok per Grade & Gender</h3>
        {equity.rows.length === 0 ? (
          <EmptyState message="Belum ada data (butuh grade terpasang dan gaji karyawan)." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">Grade</th><th>Gender</th><th>Jumlah</th>
                <th>Rata-rata</th><th>Median</th>
              </tr>
            </thead>
            <tbody>
              {equity.rows.map((r, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{r.grade_code} — {r.grade_name}</td>
                  <td>{r.gender}</td>
                  <td>{r.headcount}</td>
                  <td>{rupiah(r.avg_salary)}</td>
                  <td>{rupiah(r.median_salary)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold text-slate-900">Kesenjangan per Grade</h3>
        {equity.gaps.length === 0 ? (
          <EmptyState message="Belum ada grade dengan data kedua gender." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">Grade</th><th>Rata-rata Laki-laki</th>
                <th>Rata-rata Perempuan</th><th>Gap</th>
              </tr>
            </thead>
            <tbody>
              {equity.gaps.map((g, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{g.grade_code} — {g.grade_name}</td>
                  <td>{g.avg_laki !== null ? rupiah(g.avg_laki) : "—"}</td>
                  <td>{g.avg_perempuan !== null ? rupiah(g.avg_perempuan) : "—"}</td>
                  <td>
                    {g.gap_pct !== null ? (
                      <span className={Math.abs(g.gap_pct) > 5 ? "font-semibold text-amber-700" : ""}>
                        {g.gap_pct > 0 ? "+" : ""}{g.gap_pct}%
                      </span>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Gap positif berarti rata-rata laki-laki lebih tinggi dari perempuan pada grade yang sama.
        </p>
      </Card>
    </div>
  );
}
