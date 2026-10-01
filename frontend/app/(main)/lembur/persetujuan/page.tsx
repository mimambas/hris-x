"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { OvertimeRequest, Person, Employment } from "@/lib/types";
import { tanggal } from "@/lib/format";
import {
  PageHeader,
  Spinner,
  ErrorBox,
  EmptyState,
  StatusChip,
  Modal,
  inputCls,
  btnSmall,
  btnPrimary,
  btnSecondary,
} from "@/components/ui";

interface Pending extends OvertimeRequest {
  personName: string;
}

function jam(iso: string | null): string {
  if (!iso) return "—";
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : iso;
}

export default function PersetujuanLemburPage() {
  const [items, setItems] = useState<Pending[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [approving, setApproving] = useState<Pending | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [s1, s2, persons, emps] = await Promise.all([
        apiFetch<OvertimeRequest[]>("/overtime/requests?status=submitted"),
        apiFetch<OvertimeRequest[]>("/overtime/requests?status=approved_l1"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      const empPerson = new Map(emps.map((e) => [e.id, e.person_id]));
      const personMap = new Map(persons.map((p) => [p.id, p.full_name]));
      const all = [...s1, ...s2].map((r) => ({
        ...r,
        personName: personMap.get(empPerson.get(r.employment_id) ?? "") ?? "—",
      }));
      // Urutkan terbaru dulu.
      all.sort((a, b) => (a.date < b.date ? 1 : -1));
      setItems(all);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal memuat antrean persetujuan."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nextLevel = (r: Pending) => (r.status === "submitted" ? "l1" : "l2");

  async function approve(r: Pending) {
    const lvl = nextLevel(r);
    setBusyId(r.id);
    setActionError(null);
    setSuccessMsg(null);
    try {
      const updated = await apiFetch<OvertimeRequest>(
        `/overtime/requests/${r.id}/approve-${lvl}`,
        { method: "POST", body: JSON.stringify({ reason: "" }) }
      );
      setItems((list) =>
        list
          .map((x) => (x.id === r.id ? { ...x, ...updated } : x))
          .filter((x) => x.status === "submitted" || x.status === "approved_l1")
      );
      setSuccessMsg(
        `Pengajuan lembur ${r.personName} disetujui (${
          lvl === "l1" ? "level 1" : "level 2 (final)"
        }).`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menyetujui.");
    } finally {
      setBusyId(null);
      setApproving(null);
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
      await apiFetch<OvertimeRequest>(`/overtime/requests/${r.id}/reject`, {
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
        title="Persetujuan lembur"
        subtitle={`${items.length} pengajuan menunggu persetujuan Anda`}
      />

      {actionError && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {actionError}
        </div>
      )}

      {successMsg && (
        <div className="mb-4 rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800">
          {successMsg}
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
                <th className="px-4 py-3 text-left font-medium text-slate-600">Tanggal</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Jam</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Durasi</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Status</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Alasan pemohon</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{r.personName}</td>
                  <td className="px-4 py-3 text-slate-600">{tanggal(r.date)}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {jam(r.start_time)}–{jam(r.end_time)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {String(r.hours).replace(".", ",")} jam
                  </td>
                  <td className="px-4 py-3">
                    <StatusChip status={r.status} />
                  </td>
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
                          onClick={() => {
                            setApproving(r);
                            setActionError(null);
                            setSuccessMsg(null);
                          }}
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

      {approving && (
        <Modal
          title="Setujui pengajuan lembur"
          onClose={() => (busyId ? null : setApproving(null))}
          actions={
            <>
              <button
                onClick={() => setApproving(null)}
                disabled={busyId !== null}
                className={btnSecondary}
              >
                Batal
              </button>
              <button
                onClick={() => approve(approving)}
                disabled={busyId !== null}
                className={btnPrimary}
              >
                {busyId ? "Memproses…" : "Ya, setujui"}
              </button>
            </>
          }
        >
          <p>
            Setujui pengajuan lembur <strong>{approving.personName}</strong> (
            {tanggal(approving.date)}, {jam(approving.start_time)}–
            {jam(approving.end_time)},{" "}
            {String(approving.hours).replace(".", ",")} jam,{" "}
            {nextLevel(approving) === "l1" ? "level 1" : "level 2 (final, upah dihitung)"}
            )?
          </p>
          {nextLevel(approving) === "l2" && (
            <p className="mt-2 text-sm text-slate-600">
              Estimasi upah akan dihitung otomatis dari gaji pokok karyawan
              (jam pertama 1,5×, jam berikutnya 2×).
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
