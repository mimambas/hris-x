"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import { useAuth } from "@/components/AuthContext";
import type {
  LeaveRequest,
  LeaveType,
  LeaveBalance,
  Person,
  Employment,
} from "@/lib/types";
import { tanggal } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  StatusChip,
  Field,
  inputCls,
  btnPrimary,
} from "@/components/ui";

export default function CutiPage() {
  const { user } = useAuth();
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [requests, setRequests] = useState<LeaveRequest[]>([]);
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [employmentId, setEmploymentId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const year = new Date().getFullYear();

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [lt, reqs, me, persons, emps] = await Promise.all([
        apiFetch<LeaveType[]>("/leave/types"),
        apiFetch<LeaveRequest[]>("/leave/requests"),
        apiFetch<{ email: string }>("/me"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      setTypes(lt.filter((t) => t.is_active));
      setRequests(reqs);
      // Cari employment milik user lewat kecocokan email person.
      const person = persons.find(
        (p) => (p.email ?? "").toLowerCase() === me.email.toLowerCase()
      );
      const mine = emps.filter(
        (e) => person && e.person_id === person.id && e.status === "active"
      );
      const chosen = mine[0]?.id ?? emps[0]?.id ?? "";
      setEmploymentId(chosen);
      if (chosen) {
        const bal = await apiFetch<LeaveBalance[]>(
          `/leave/balances?employment_id=${chosen}&year=${year}`
        );
        setBalances(bal);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data cuti.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const typeName = useMemo(() => {
    const m = new Map(types.map((t) => [t.id, t.name]));
    return (id: string) => m.get(id) ?? "—";
  }, [types]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!employmentId) {
      setFormError("Data employment Anda tidak ditemukan. Hubungi HR.");
      return;
    }
    if (startDate > endDate) {
      setFormError("Tanggal mulai tidak boleh setelah tanggal selesai.");
      return;
    }
    setBusy(true);
    try {
      const created = await apiFetch<LeaveRequest>("/leave/requests?source=web", {
        method: "POST",
        body: JSON.stringify({
          employment_id: employmentId,
          leave_type_id: leaveTypeId,
          start_date: startDate,
          end_date: endDate,
          reason: reason.trim() || null,
        }),
      });
      // Langsung submit agar masuk antrean persetujuan.
      const submitted = await apiFetch<LeaveRequest>(
        `/leave/requests/${created.id}/submit`,
        { method: "POST" }
      );
      setRequests((r) => [submitted, ...r]);
      setLeaveTypeId("");
      setStartDate("");
      setEndDate("");
      setReason("");
      const bal = await apiFetch<LeaveBalance[]>(
        `/leave/balances?employment_id=${employmentId}&year=${year}`
      );
      setBalances(bal);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal mengajukan cuti.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Memuat data cuti…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Cuti"
        subtitle="Ajukan cuti dan pantau status pengajuan Anda"
        action={
          <Link href="/cuti/persetujuan" className="text-sm font-medium text-brand-600 hover:text-brand-700">
            Ke halaman persetujuan →
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Pengajuan cuti baru" className="lg:col-span-2">
          {formError && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {formError}
            </div>
          )}
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Jenis cuti" required>
              <select
                className={inputCls}
                value={leaveTypeId}
                onChange={(e) => setLeaveTypeId(e.target.value)}
                required
              >
                <option value="">— Pilih jenis cuti —</option>
                {types.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.quota_days} hari)
                  </option>
                ))}
              </select>
            </Field>
            <div />
            <Field label="Tanggal mulai" required>
              <input
                className={inputCls}
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                required
              />
            </Field>
            <Field label="Tanggal selesai" required>
              <input
                className={inputCls}
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                required
              />
            </Field>
            <div className="md:col-span-2">
              <Field label="Alasan">
                <textarea
                  className={inputCls}
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Tuliskan alasan pengajuan cuti…"
                />
              </Field>
            </div>
            <div className="md:col-span-2">
              <button type="submit" disabled={busy} className={btnPrimary}>
                {busy ? "Mengirim…" : "Ajukan cuti"}
              </button>
              <p className="mt-2 text-xs text-slate-500">
                Pengajuan otomatis disubmit dan diteruskan ke atasan untuk persetujuan
                level 1.
              </p>
            </div>
          </form>
        </Card>

        <Card title={`Saldo cuti ${year}`}>
          {balances.length === 0 ? (
            <EmptyState message="Belum ada data saldo." />
          ) : (
            <ul className="space-y-3">
              {balances.map((b) => (
                <li key={b.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                  <p className="font-medium text-slate-900">{typeName(b.leave_type_id)}</p>
                  <p className="mt-1 text-slate-600">
                    Sisa <span className="font-semibold text-brand-700">{b.remaining}</span>{" "}
                    dari {b.entitled} hari · terpakai {b.used}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Pengajuan saya">
          {requests.length === 0 ? (
            <EmptyState message="Belum ada pengajuan cuti." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Jenis</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Periode</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Hari</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Status</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Alasan</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {requests.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-medium text-slate-900">{typeName(r.leave_type_id)}</td>
                      <td className="px-4 py-3 text-slate-600">
                        {tanggal(r.start_date)} s.d. {tanggal(r.end_date)}
                      </td>
                      <td className="px-4 py-3 text-slate-600">{r.days}</td>
                      <td className="px-4 py-3"><StatusChip status={r.status} /></td>
                      <td className="px-4 py-3 text-slate-600">{r.reason ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
