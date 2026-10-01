"use client";

import { useAuth } from "@/components/AuthContext";
import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Employment, Loan, Person } from "@/lib/types";
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

interface Item extends Loan {
  personName: string;
}

export default function PersetujuanPinjamanPage() {
  const { user } = useAuth();
  // Persetujuan & penolakan pinjaman hanya boleh oleh HR/Finance.
  const isHr = user?.is_hr ?? user?.is_superadmin ?? false;
  const [queue, setQueue] = useState<Item[]>([]);
  const [berjalan, setBerjalan] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [modal, setModal] = useState<{ item: Item; kind: "approve" | "reject" } | null>(null);
  const [reason, setReason] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [submitted, actives, persons, emps] = await Promise.all([
        apiFetch<Loan[]>("/loans?status=submitted"),
        apiFetch<Loan[]>("/loans?status=active"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      const empPerson = new Map(emps.map((e) => [e.id, e.person_id]));
      const personMap = new Map(persons.map((p) => [p.id, p.full_name]));
      const enrich = (l: Loan): Item => ({
        ...l,
        personName: personMap.get(empPerson.get(l.employment_id) ?? "") ?? "—",
      });
      setQueue(submitted.map(enrich));
      // "Pinjaman berjalan" mengikuti aturan backend: status submitted +
      // active dihitung sebagai pemblokir pengajuan baru (anti ganda).
      setBerjalan([...submitted, ...actives].map(enrich));
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

  async function doAction() {
    if (!modal) return;
    if (modal.kind === "reject" && !reason.trim()) {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    setBusyId(modal.item.id);
    setActionError(null);
    try {
      await apiFetch(`/loans/${modal.item.id}/${modal.kind}`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() || null }),
      });
      setSuccessMsg(
        modal.kind === "approve"
          ? "Pinjaman disetujui dan menjadi aktif."
          : "Pinjaman ditolak."
      );
      setModal(null);
      setReason("");
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner label="Memuat antrean persetujuan…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Persetujuan pinjaman"
        subtitle="Persetujuan HR/Finance dan daftar pinjaman berjalan."
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

      <div className="space-y-6">
        <Card
          title="Menunggu persetujuan HR/Finance"
          subtitle={`${queue.length} pengajuan`}
        >
          {queue.length === 0 ? (
            <EmptyState message="Tidak ada pengajuan menunggu persetujuan." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase text-slate-500">
                    <th className="py-2 pr-3">Karyawan</th>
                    <th className="py-2 pr-3 text-right">Nominal</th>
                    <th className="py-2 pr-3">Tenor</th>
                    <th className="py-2 pr-3 text-right">Cicilan/bln</th>
                    <th className="py-2">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((l) => (
                    <tr key={l.id} className="border-b last:border-0">
                      <td className="py-2 pr-3">
                        <p className="font-medium">{l.personName}</p>
                        <p className="text-xs text-slate-500">
                          Diajukan {tanggal(l.submitted_at)}
                          {l.purpose ? ` · ${l.purpose}` : ""}
                        </p>
                      </td>
                      <td className="py-2 pr-3 text-right font-medium">
                        {rupiah(l.principal_amount)}
                      </td>
                      <td className="py-2 pr-3">{l.tenor_months} bulan</td>
                      <td className="py-2 pr-3 text-right">
                        {rupiah(l.monthly_installment)}
                      </td>
                      <td className="py-2">
                        {isHr ? (
                          <div className="flex gap-1">
                            <button
                              className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                              disabled={busyId === l.id}
                              onClick={() => {
                                setReason("");
                                setModal({ item: l, kind: "approve" });
                              }}
                            >
                              Setujui
                            </button>
                            <button
                              className={`${btnSmall} bg-red-600 text-white hover:bg-red-700`}
                              disabled={busyId === l.id}
                              onClick={() => {
                                setReason("");
                                setModal({ item: l, kind: "reject" });
                              }}
                            >
                              Tolak
                            </button>
                          </div>
                        ) : (
                          <span className="text-xs text-slate-500">
                            Menunggu persetujuan HR/Finance
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card
          title="Pinjaman berjalan"
          subtitle={`${berjalan.length} pinjaman · menunggu persetujuan + aktif`}
        >
          {berjalan.length === 0 ? (
            <EmptyState message="Tidak ada pinjaman berjalan." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase text-slate-500">
                    <th className="py-2 pr-3">Karyawan</th>
                    <th className="py-2 pr-3 text-right">Pokok</th>
                    <th className="py-2 pr-3 text-right">Sisa</th>
                    <th className="py-2 pr-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {berjalan.map((l) => (
                    <tr key={l.id} className="border-b last:border-0">
                      <td className="py-2 pr-3 font-medium">{l.personName}</td>
                      <td className="py-2 pr-3 text-right">
                        {rupiah(l.principal_amount)}
                      </td>
                      <td className="py-2 pr-3 text-right font-medium">
                        {rupiah(l.remaining_total)}
                      </td>
                      <td className="py-2">
                        <LoanStatusChip status={l.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {modal && (
        <Modal
          title={modal.kind === "approve" ? "Setujui pinjaman" : "Tolak pinjaman"}
          onClose={() => busyId == null && setModal(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                disabled={busyId != null}
                onClick={() => setModal(null)}
              >
                Batal
              </button>
              <button
                className={modal.kind === "reject" ? btnDanger : btnPrimary}
                disabled={busyId != null}
                onClick={doAction}
              >
                {busyId != null ? "Memproses…" : "Ya, lanjutkan"}
              </button>
            </>
          }
        >
          <p className="mb-3">
            {modal.item.personName} ·{" "}
            <span className="font-semibold">
              {rupiah(modal.item.principal_amount)}
            </span>{" "}
            · {modal.item.tenor_months} bulan
          </p>
          <Field
            label="Catatan / alasan"
            required={modal.kind === "reject"}
          >
            <textarea
              className={inputCls}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Tulis catatan…"
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
