"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  Employment,
  Loan,
  LoanInstallment,
  LoanPolicy,
  Me,
  Person,
} from "@/lib/types";
import { rupiah, tanggal } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  LoanStatusChip,
  Field,
  Modal,
  inputCls,
  btnPrimary,
  btnSecondary,
  btnDanger,
  btnSmall,
} from "@/components/ui";

export default function PinjamanPage() {
  const [policy, setPolicy] = useState<LoanPolicy | null>(null);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [employmentId, setEmploymentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [amount, setAmount] = useState("");
  const [tenor, setTenor] = useState("");
  const [purpose, setPurpose] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [payoffTarget, setPayoffTarget] = useState<Loan | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [installments, setInstallments] = useState<Record<string, LoanInstallment[]>>({});
  const [instLoading, setInstLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [pol, me, persons, emps] = await Promise.all([
        apiFetch<LoanPolicy>("/loans/policy"),
        apiFetch<Me>("/me"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      setPolicy(pol);
      const mePersonId =
        me.person_id ??
        persons.find(
          (p) => (p.email ?? "").toLowerCase() === me.email.toLowerCase()
        )?.id;
      const mine = emps.filter(
        (e) =>
          mePersonId != null && e.person_id === mePersonId && e.status === "active"
      );
      const chosen = mine[0]?.id ?? "";
      setEmploymentId(chosen);
      if (!chosen) {
        setError("Akun Anda tidak terhubung ke data karyawan.");
        return;
      }
      const myLoans = await apiFetch<Loan[]>(
        `/loans?employment_id=${chosen}`
      );
      setLoans(myLoans);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data pinjaman.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitNew() {
    setFormError(null);
    const nominal = parseInt(amount, 10);
    const tenorBln = parseInt(tenor, 10);
    if (!nominal || nominal <= 0)
      return setFormError("Nominal harus lebih dari 0.");
    if (!tenorBln || tenorBln <= 0)
      return setFormError("Tenor harus lebih dari 0 bulan.");
    setBusy(true);
    try {
      const created = await apiFetch<Loan>("/loans", {
        method: "POST",
        body: JSON.stringify({
          employment_id: employmentId,
          amount: nominal,
          tenor_months: tenorBln,
          purpose: purpose.trim() || null,
        }),
      });
      await apiFetch<Loan>(`/loans/${created.id}/submit`, { method: "POST" });
      setShowForm(false);
      setAmount("");
      setTenor("");
      setPurpose("");
      setSuccessMsg("Pinjaman berhasil diajukan dan menunggu persetujuan HR.");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal mengajukan pinjaman.");
    } finally {
      setBusy(false);
    }
  }

  async function doSimple(id: string, action: "submit" | "cancel") {
    setBusyId(id);
    setActionError(null);
    try {
      await apiFetch(`/loans/${id}/${action}`, { method: "POST" });
      setSuccessMsg(
        action === "submit" ? "Pinjaman diajukan ke HR." : "Pengajuan pinjaman dibatalkan."
      );
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  async function doPayoff() {
    if (!payoffTarget) return;
    setBusyId(payoffTarget.id);
    setActionError(null);
    try {
      const inst = await apiFetch<LoanInstallment>(
        `/loans/${payoffTarget.id}/payoff`,
        { method: "POST" }
      );
      setSuccessMsg(
        `Pelunasan dipercepat dijadwalkan pada periode ${inst.period} sebesar ${rupiah(inst.amount)}.`
      );
      setPayoffTarget(null);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Pelunasan gagal.");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleInstallments(loan: Loan) {
    if (expanded === loan.id) {
      setExpanded(null);
      return;
    }
    setExpanded(loan.id);
    if (installments[loan.id]) return;
    setInstLoading(true);
    try {
      const rows = await apiFetch<LoanInstallment[]>(
        `/loans/${loan.id}/installments`
      );
      setInstallments((prev) => ({ ...prev, [loan.id]: rows }));
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal memuat cicilan."
      );
    } finally {
      setInstLoading(false);
    }
  }

  if (loading) return <Spinner label="Memuat data pinjaman…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Pinjaman saya"
        subtitle="Pengajuan pinjaman karyawan, cicilan, dan pelunasan."
        action={
          <button className={btnPrimary} onClick={() => setShowForm(true)}>
            + Ajukan pinjaman
          </button>
        }
      />

      {successMsg && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
          {successMsg}
        </div>
      )}
      {actionError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {actionError}
        </div>
      )}

      {policy && (
        <Card
          title="Kebijakan pinjaman"
          subtitle="Batas yang berlaku di perusahaan Anda."
          className="mb-6"
        >
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">Maksimal nominal</p>
              <p className="font-semibold">
                {policy.max_amount_multiplier}× gaji pokok
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Maksimal tenor</p>
              <p className="font-semibold">{policy.max_tenor_months} bulan</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Bunga flat</p>
              <p className="font-semibold">
                {policy.default_interest_rate}% per bulan
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Pinjaman berjalan</p>
              <p className="font-semibold">
                {policy.allow_multiple_active ? "Boleh lebih dari 1" : "Maks 1 per karyawan"}
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="space-y-4">
        {loans.length === 0 && (
          <EmptyState message="Belum ada pengajuan pinjaman." />
        )}
        {loans.map((l) => {
          const progress =
            l.total_payable > 0
              ? Math.min(
                  100,
                  Math.round(
                    ((l.total_payable - l.remaining_total) / l.total_payable) * 100
                  )
                )
              : 0;
          return (
            <Card
              key={l.id}
              title={`${rupiah(l.principal_amount)} · ${l.tenor_months} bulan`}
              subtitle={`Diajukan ${tanggal(l.created_at)}${l.purpose ? ` · ${l.purpose}` : ""}`}
              action={<LoanStatusChip status={l.status} />}
            >
              <div className="grid gap-3 text-sm sm:grid-cols-3">
                <div>
                  <p className="text-xs text-slate-500">Cicilan per bulan</p>
                  <p className="font-semibold">{rupiah(l.monthly_installment)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Sisa total</p>
                  <p className="font-semibold">{rupiah(l.remaining_total)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Bunga</p>
                  <p className="font-semibold">{l.interest_rate}% per bulan</p>
                </div>
              </div>
              {(l.status === "active" || l.status === "completed") && (
                <div className="mt-3">
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-brand-600"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Terbayar {progress}% dari {rupiah(l.total_payable)}
                  </p>
                </div>
              )}
              {l.rejection_reason && (
                <p className="mt-2 text-sm text-red-600">
                  Alasan tolak: {l.rejection_reason}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className={`${btnSmall} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}
                  onClick={() => toggleInstallments(l)}
                >
                  {expanded === l.id ? "Sembunyikan cicilan" : "Lihat cicilan"}
                </button>
                {l.status === "draft" && (
                  <button
                    className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                    disabled={busyId === l.id}
                    onClick={() => doSimple(l.id, "submit")}
                  >
                    Ajukan
                  </button>
                )}
                {(l.status === "draft" || l.status === "submitted") && (
                  <button
                    className={`${btnSmall} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}
                    disabled={busyId === l.id}
                    onClick={() => doSimple(l.id, "cancel")}
                  >
                    Batalkan
                  </button>
                )}
                {l.status === "active" && (
                  <button
                    className={`${btnSmall} bg-emerald-600 text-white hover:bg-emerald-700`}
                    disabled={busyId === l.id}
                    onClick={() => setPayoffTarget(l)}
                  >
                    Lunasi sekarang
                  </button>
                )}
              </div>
              {expanded === l.id && (
                <div className="mt-4 border-t pt-3">
                  {instLoading && !installments[l.id] ? (
                    <p className="text-sm text-slate-500">Memuat cicilan…</p>
                  ) : (installments[l.id] ?? []).length === 0 ? (
                    <p className="text-sm text-slate-500">
                      Belum ada jadwal cicilan (dibuat per periode payroll).
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b text-left text-xs uppercase text-slate-500">
                            <th className="py-2 pr-3">Periode</th>
                            <th className="py-2 pr-3 text-right">Nominal</th>
                            <th className="py-2 pr-3">Jenis</th>
                            <th className="py-2">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {installments[l.id].map((ins) => (
                            <tr key={ins.id} className="border-b last:border-0">
                              <td className="py-2 pr-3">{ins.period}</td>
                              <td className="py-2 pr-3 text-right font-medium">
                                {rupiah(ins.amount)}
                              </td>
                              <td className="py-2 pr-3">
                                {ins.kind === "payoff" ? "Pelunasan" : "Cicilan"}
                              </td>
                              <td className="py-2">
                                {ins.status === "paid" ? (
                                  <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-inset ring-emerald-300">
                                    Dibayar
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-300">
                                    Menunggu
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {showForm && (
        <Modal
          title="Ajukan pinjaman"
          onClose={() => !busy && setShowForm(false)}
          actions={
            <>
              <button
                className={btnSecondary}
                disabled={busy}
                onClick={() => setShowForm(false)}
              >
                Batal
              </button>
              <button className={btnPrimary} disabled={busy} onClick={submitNew}>
                {busy ? "Mengirim…" : "Kirim pengajuan"}
              </button>
            </>
          }
        >
          <div className="space-y-4">
            {formError && (
              <div className="rounded-md border border-red-200 bg-red-50 p-2.5 text-sm text-red-800">
                {formError}
              </div>
            )}
            {policy && (
              <p className="rounded-md bg-slate-50 p-2.5 text-xs text-slate-600">
                Batas: maksimal {policy.max_amount_multiplier}× gaji pokok,
                tenor maksimal {policy.max_tenor_months} bulan.
              </p>
            )}
            <Field label="Nominal pinjaman (Rp)" required>
              <input
                className={inputCls}
                type="number"
                min={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="12000000"
              />
            </Field>
            <Field label="Tenor (bulan)" required>
              <input
                className={inputCls}
                type="number"
                min={1}
                max={policy?.max_tenor_months ?? 24}
                value={tenor}
                onChange={(e) => setTenor(e.target.value)}
                placeholder="12"
              />
            </Field>
            <Field label="Keperluan">
              <textarea
                className={inputCls}
                rows={2}
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                placeholder="cth. Biaya pendidikan anak"
              />
            </Field>
          </div>
        </Modal>
      )}

      {payoffTarget && (
        <Modal
          title="Lunasi pinjaman sekarang"
          onClose={() => busyId == null && setPayoffTarget(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                disabled={busyId != null}
                onClick={() => setPayoffTarget(null)}
              >
                Batal
              </button>
              <button
                className={btnDanger}
                disabled={busyId != null}
                onClick={doPayoff}
              >
                {busyId != null ? "Memproses…" : "Ya, lunasi"}
              </button>
            </>
          }
        >
          <p>
            Sisa {rupiah(payoffTarget.remaining_total)} akan dijadwalkan sebagai
            pelunasan pada periode payroll terbuka berikutnya dan dipotong dari
            gaji Anda.
          </p>
        </Modal>
      )}
    </div>
  );
}
