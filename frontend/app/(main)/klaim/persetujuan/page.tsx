"use client";

import { useAuth } from "@/components/AuthContext";
import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Claim, ClaimType, Employment, Person } from "@/lib/types";
import { rupiah, tanggal } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  ClaimStatusChip,
  Field,
  Modal,
  inputCls,
  btnPrimary,
  btnSecondary,
  btnDanger,
  btnSmall,
} from "@/components/ui";

interface Item extends Claim {
  personName: string;
  typeName: string;
}

type ActKind = "approve_l1" | "approve" | "reject" | "mark_paid";

export default function PersetujuanKlaimPage() {
  const { user } = useAuth();
  // Approve final & tandai dibayar hanya boleh oleh HR.
  const isHr = user?.is_hr ?? user?.is_superadmin ?? false;
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [modal, setModal] = useState<{ item: Item; kind: ActKind } | null>(null);
  const [reason, setReason] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [s1, s2, s3, types, persons, emps] = await Promise.all([
        apiFetch<Claim[]>("/claims?status=submitted"),
        apiFetch<Claim[]>("/claims?status=approved_l1"),
        apiFetch<Claim[]>("/claims?status=approved"),
        apiFetch<ClaimType[]>("/claims/types"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      const typeMap = new Map(types.map((t) => [t.id, t.name]));
      const empPerson = new Map(emps.map((e) => [e.id, e.person_id]));
      const personMap = new Map(persons.map((p) => [p.id, p.full_name]));
      const all = [...s1, ...s2, ...s3].map((c) => ({
        ...c,
        personName:
          personMap.get(empPerson.get(c.employment_id) ?? "") ?? "—",
        typeName: typeMap.get(c.claim_type_id) ?? "—",
      }));
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

  async function doAction() {
    if (!modal) return;
    if (modal.kind === "reject" && !reason.trim()) {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    const { item, kind } = modal;
    setBusyId(item.id);
    setActionError(null);
    try {
      const body =
        kind === "mark_paid"
          ? { payment_ref: reason.trim() || null }
          : { reason: reason.trim() || null };
      await apiFetch(`/claims/${item.id}/${kind.replace("_", "-")}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const labels: Record<ActKind, string> = {
        approve_l1: "Klaim disetujui L1 (diteruskan ke HR/Finance).",
        approve: "Klaim disetujui final.",
        reject: "Klaim ditolak.",
        mark_paid: "Klaim ditandai sudah dibayar.",
      };
      setSuccessMsg(labels[kind]);
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

  const l1 = items.filter((i) => i.status === "submitted");
  const l2 = items.filter((i) => i.status === "approved_l1");
  const pay = items.filter((i) => i.status === "approved");

  function row(c: Item, actions: React.ReactNode) {
    return (
      <tr key={c.id} className="border-b last:border-0">
        <td className="py-2 pr-3">
          <p className="font-medium">{c.personName}</p>
          <p className="text-xs text-slate-500">{tanggal(c.claim_date)}</p>
        </td>
        <td className="py-2 pr-3">
          {c.typeName}
          {c.description && (
            <p className="text-xs text-slate-500">{c.description}</p>
          )}
        </td>
        <td className="py-2 pr-3 text-right font-medium">{rupiah(c.amount)}</td>
        <td className="py-2 pr-3">
          <ClaimStatusChip status={c.status} />
        </td>
        <td className="py-2">
          <div className="flex flex-wrap gap-1">{actions}</div>
        </td>
      </tr>
    );
  }

  function table(list: Item[], kind: "l1" | "l2" | "pay", empty: string) {
    if (list.length === 0) return <EmptyState message={empty} />;
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase text-slate-500">
              <th className="py-2 pr-3">Karyawan</th>
              <th className="py-2 pr-3">Jenis</th>
              <th className="py-2 pr-3 text-right">Nominal</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {list.map((c) =>
              row(
                c,
                <>
                  {kind === "l1" && (
                    <button
                      className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                      disabled={busyId === c.id}
                      onClick={() => {
                        setReason("");
                        setModal({ item: c, kind: "approve_l1" });
                      }}
                    >
                      Setujui L1
                    </button>
                  )}
                  {kind === "l2" && isHr && (
                    <button
                      className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                      disabled={busyId === c.id}
                      onClick={() => {
                        setReason("");
                        setModal({ item: c, kind: "approve" });
                      }}
                    >
                      Setujui final
                    </button>
                  )}
                  {kind === "l2" && !isHr && (
                    <span className="text-xs text-slate-500">
                      Menunggu persetujuan HR/Finance
                    </span>
                  )}
                  {kind === "pay" && isHr && (
                    <button
                      className={`${btnSmall} bg-emerald-600 text-white hover:bg-emerald-700`}
                      disabled={busyId === c.id}
                      onClick={() => {
                        setReason("");
                        setModal({ item: c, kind: "mark_paid" });
                      }}
                    >
                      Tandai dibayar
                    </button>
                  )}
                  {kind !== "pay" && (
                    <button
                      className={`${btnSmall} bg-red-600 text-white hover:bg-red-700`}
                      disabled={busyId === c.id}
                      onClick={() => {
                        setReason("");
                        setModal({ item: c, kind: "reject" });
                      }}
                    >
                      Tolak
                    </button>
                  )}
                </>
              )
            )}
          </tbody>
        </table>
      </div>
    );
  }

  const modalTitle: Record<ActKind, string> = {
    approve_l1: "Setujui klaim (L1)",
    approve: "Setujui klaim (final)",
    reject: "Tolak klaim",
    mark_paid: "Tandai klaim dibayar",
  };

  return (
    <div>
      <PageHeader
        title="Persetujuan klaim"
        subtitle="Antrean persetujuan atasan (L1), HR/Finance (final), dan pembayaran."
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
          title="Menunggu persetujuan atasan (L1)"
          subtitle={`${l1.length} pengajuan`}
        >
          {table(l1, "l1", "Tidak ada pengajuan menunggu L1.")}
        </Card>
        <Card
          title="Menunggu persetujuan final (HR/Finance)"
          subtitle={`${l2.length} pengajuan`}
        >
          {table(l2, "l2", "Tidak ada pengajuan menunggu final.")}
        </Card>
        <Card title="Menunggu pembayaran" subtitle={`${pay.length} pengajuan`}>
          {table(pay, "pay", "Tidak ada klaim menunggu pembayaran.")}
        </Card>
      </div>

      {modal && (
        <Modal
          title={modalTitle[modal.kind]}
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
                className={
                  modal.kind === "reject" ? btnDanger : btnPrimary
                }
                disabled={busyId != null}
                onClick={doAction}
              >
                {busyId != null ? "Memproses…" : "Ya, lanjutkan"}
              </button>
            </>
          }
        >
          <p className="mb-3">
            {modal.item.personName} · {modal.item.typeName} ·{" "}
            <span className="font-semibold">{rupiah(modal.item.amount)}</span>
          </p>
          <Field
            label={
              modal.kind === "reject"
                ? "Alasan penolakan"
                : modal.kind === "mark_paid"
                ? "Referensi pembayaran (opsional)"
                : "Catatan (opsional)"
            }
            required={modal.kind === "reject"}
          >
            <textarea
              className={inputCls}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                modal.kind === "mark_paid"
                  ? "cth. TRX-2026-1001"
                  : "Tulis catatan…"
              }
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
