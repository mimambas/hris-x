"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { LeaveRequest, LeaveType, Person, Employment } from "@/lib/types";
import { tanggal } from "@/lib/format";
import {
  PageHeader,
  Spinner,
  ErrorBox,
  EmptyState,
  StatusChip,
  inputCls,
  btnSmall,
} from "@/components/ui";

interface Pending extends LeaveRequest {
  personName: string;
  typeName: string;
}

export default function PersetujuanCutiPage() {
  const [items, setItems] = useState<Pending[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [s1, s2, types, persons, emps] = await Promise.all([
        apiFetch<LeaveRequest[]>("/leave/requests?status=submitted"),
        apiFetch<LeaveRequest[]>("/leave/requests?status=approved_l1"),
        apiFetch<LeaveType[]>("/leave/types"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      const typeMap = new Map(types.map((t) => [t.id, t.name]));
      const empPerson = new Map(emps.map((e) => [e.id, e.person_id]));
      const personMap = new Map(persons.map((p) => [p.id, p.full_name]));
      const all = [...s1, ...s2].map((r) => ({
        ...r,
        personName: personMap.get(empPerson.get(r.employment_id) ?? "") ?? "—",
        typeName: typeMap.get(r.leave_type_id) ?? "—",
      }));
      setItems(all);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat antrean persetujuan.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nextLevel = useMemo(() => {
    return (r: Pending) => (r.status === "submitted" ? "l1" : "l2");
  }, []);

  async function approve(r: Pending) {
    const lvl = nextLevel(r);
    const label = lvl === "l1" ? "level 1" : "level 2";
    if (!confirm(`Setujui pengajuan cuti ${r.personName} (${label})?`)) return;
    setBusyId(r.id);
    setActionError(null);
    try {
      const updated = await apiFetch<LeaveRequest>(
        `/leave/requests/${r.id}/approve-${lvl}`,
        { method: "POST", body: JSON.stringify({ reason: "" }) }
      );
      setItems((list) =>
        list.map((x) =>
          x.id === r.id ? { ...x, ...updated } : x
        ).filter((x) => x.status === "submitted" || x.status === "approved_l1")
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menyetujui.");
    } finally {
      setBusyId(null);
    }
  }

  async function reject(r: Pending) {
    if (!rejectReason.trim()) {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    setBusyId(r.id);
    setActionError(null);
    try {
      await apiFetch<LeaveRequest>(`/leave/requests/${r.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason.trim() }),
      });
      setItems((list) => list.filter((x) => x.id !== r.id));
      setRejectingId(null);
      setRejectReason("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menolak.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner label="Memuat antrean persetujuan…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Persetujuan cuti"
        subtitle={`${items.length} pengajuan menunggu persetujuan Anda`}
      />

      {actionError && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {actionError}
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState message="Tidak ada pengajuan yang menunggu persetujuan." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Karyawan</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Jenis</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Periode</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Hari</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Status</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Alasan pemohon</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{r.personName}</td>
                  <td className="px-4 py-3 text-slate-600">{r.typeName}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {tanggal(r.start_date)} s.d. {tanggal(r.end_date)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{r.days}</td>
                  <td className="px-4 py-3"><StatusChip status={r.status} /></td>
                  <td className="px-4 py-3 text-slate-600">{r.reason ?? "-"}</td>
                  <td className="px-4 py-3">
                    {rejectingId === r.id ? (
                      <div className="min-w-56 space-y-2">
                        <input
                          className={inputCls}
                          placeholder="Alasan penolakan (wajib)"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          autoFocus
                        />
                        <div className="flex gap-2">
                          <button
                            onClick={() => reject(r)}
                            disabled={busyId === r.id}
                            className={`${btnSmall} bg-red-600 text-white hover:bg-red-700`}
                          >
                            {busyId === r.id ? "…" : "Tolak"}
                          </button>
                          <button
                            onClick={() => {
                              setRejectingId(null);
                              setRejectReason("");
                            }}
                            className={`${btnSmall} border border-slate-300 bg-white text-slate-700`}
                          >
                            Batal
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <button
                          onClick={() => approve(r)}
                          disabled={busyId === r.id}
                          className={`${btnSmall} bg-green-600 text-white hover:bg-green-700`}
                        >
                          {busyId === r.id ? "…" : `Setujui${nextLevel(r) === "l1" ? " L1" : " L2"}`}
                        </button>
                        <button
                          onClick={() => {
                            setRejectingId(r.id);
                            setRejectReason("");
                          }}
                          disabled={busyId === r.id}
                          className={`${btnSmall} border border-red-300 bg-white text-red-700 hover:bg-red-50`}
                        >
                          Tolak
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
