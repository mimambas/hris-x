"use client";

import { useEffect, useState } from "react";
import { apiFetch, apiUploadForm, ApiError } from "@/lib/api";
import type {
  Claim,
  ClaimType,
  ClaimSummary,
  Document,
  Employment,
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
  ClaimStatusChip,
  Field,
  Modal,
  inputCls,
  btnPrimary,
  btnSecondary,
  btnSmall,
} from "@/components/ui";

const year = new Date().getFullYear();

export default function KlaimPage() {
  const [types, setTypes] = useState<ClaimType[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [summary, setSummary] = useState<ClaimSummary[]>([]);
  const [employmentId, setEmploymentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form ajukan klaim
  const [showForm, setShowForm] = useState(false);
  const [claimTypeId, setClaimTypeId] = useState("");
  const [amount, setAmount] = useState("");
  const [claimDate, setClaimDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [description, setDescription] = useState("");
  const [paidVia, setPaidVia] = useState("payroll");
  const [receipt, setReceipt] = useState<File | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [busyId, setBusyId] = useState<string | null>(null);

  const typeMap = new Map(types.map((t) => [t.id, t]));
  const selectedType = types.find((t) => t.id === claimTypeId);

  async function load() {
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [ct, me, persons, emps] = await Promise.all([
        apiFetch<ClaimType[]>("/claims/types"),
        apiFetch<Me>("/me"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      setTypes(ct.filter((t) => t.active));
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
      const [myClaims, sum] = await Promise.all([
        apiFetch<Claim[]>(`/claims?employment_id=${chosen}`),
        apiFetch<ClaimSummary[]>(
          `/claims/summary/yearly?employment_id=${chosen}&year=${year}`
        ),
      ]);
      setClaims(myClaims);
      setSummary(sum);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data klaim.");
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
    if (!claimTypeId) return setFormError("Pilih jenis klaim.");
    if (!nominal || nominal <= 0)
      return setFormError("Nominal harus lebih dari 0.");
    if (!claimDate) return setFormError("Tanggal klaim wajib diisi.");
    if (selectedType?.requires_receipt && !receipt)
      return setFormError("Struk wajib diunggah untuk jenis klaim ini.");
    setBusy(true);
    try {
      let receiptId: string | null = null;
      if (receipt) {
        const doc = await apiUploadForm<Document>(
          "/documents",
          {
            doc_type: "lain",
            employment_id: employmentId,
            notes: "Struk klaim",
          },
          receipt
        );
        receiptId = doc.id;
      }
      const created = await apiFetch<Claim>("/claims", {
        method: "POST",
        body: JSON.stringify({
          employment_id: employmentId,
          claim_type_id: claimTypeId,
          amount: nominal,
          claim_date: claimDate,
          description: description.trim() || null,
          receipt_document_id: receiptId,
          paid_via: paidVia,
        }),
      });
      await apiFetch<Claim>(`/claims/${created.id}/submit`, { method: "POST" });
      setShowForm(false);
      setClaimTypeId("");
      setAmount("");
      setDescription("");
      setPaidVia("payroll");
      setReceipt(null);
      setSuccessMsg("Klaim berhasil diajukan dan menunggu persetujuan atasan.");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal mengajukan klaim.");
    } finally {
      setBusy(false);
    }
  }

  async function doAction(id: string, action: "submit" | "cancel") {
    setBusyId(id);
    setActionError(null);
    try {
      await apiFetch(`/claims/${id}/${action}`, { method: "POST" });
      setSuccessMsg(
        action === "submit"
          ? "Klaim diajukan ke atasan."
          : "Pengajuan klaim dibatalkan."
      );
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner label="Memuat data klaim…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Klaim saya"
        subtitle="Pengajuan reimbursement dan sisa plafon tahunan Anda."
        action={
          <button className={btnPrimary} onClick={() => setShowForm(true)}>
            + Ajukan klaim
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

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {summary.map((s) => (
          <Card key={s.claim_type_id} title={s.claim_type_name} subtitle={`Kode: ${s.claim_type_code}`}>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-xs text-slate-500">Terpakai {year}</p>
                <p className="text-lg font-semibold text-slate-900">
                  {rupiah(s.used)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">Sisa plafon</p>
                <p className="text-lg font-semibold text-brand-700">
                  {s.remaining == null ? "Tanpa batas" : rupiah(s.remaining)}
                </p>
              </div>
            </div>
            {s.limit_per_year != null && (
              <p className="mt-1 text-xs text-slate-500">
                Plafon tahunan: {rupiah(s.limit_per_year)}
              </p>
            )}
          </Card>
        ))}
        {summary.length === 0 && (
          <div className="sm:col-span-2 lg:col-span-3">
            <EmptyState message="Belum ada data plafon klaim." />
          </div>
        )}
      </div>

      <Card title="Riwayat pengajuan" subtitle={`${claims.length} pengajuan`}>
        {claims.length === 0 ? (
          <EmptyState message="Belum ada pengajuan klaim." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-slate-500">
                  <th className="py-2 pr-3">Tanggal</th>
                  <th className="py-2 pr-3">Jenis</th>
                  <th className="py-2 pr-3 text-right">Nominal</th>
                  <th className="py-2 pr-3">Via</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="py-2 pr-3">{tanggal(c.claim_date)}</td>
                    <td className="py-2 pr-3">
                      {typeMap.get(c.claim_type_id)?.name ?? "—"}
                      {c.description && (
                        <p className="text-xs text-slate-500">{c.description}</p>
                      )}
                      {c.rejection_reason && (
                        <p className="text-xs text-red-600">
                          Alasan tolak: {c.rejection_reason}
                        </p>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right font-medium">
                      {rupiah(c.amount)}
                    </td>
                    <td className="py-2 pr-3 capitalize">{c.paid_via}</td>
                    <td className="py-2 pr-3">
                      <ClaimStatusChip status={c.status} />
                    </td>
                    <td className="py-2">
                      <div className="flex gap-1">
                        {c.status === "draft" && (
                          <button
                            className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                            disabled={busyId === c.id}
                            onClick={() => doAction(c.id, "submit")}
                          >
                            Ajukan
                          </button>
                        )}
                        {(c.status === "draft" || c.status === "submitted") && (
                          <button
                            className={`${btnSmall} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}
                            disabled={busyId === c.id}
                            onClick={() => doAction(c.id, "cancel")}
                          >
                            Batalkan
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
      </Card>

      {showForm && (
        <Modal
          title="Ajukan klaim"
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
            <Field label="Jenis klaim" required>
              <select
                className={inputCls}
                value={claimTypeId}
                onChange={(e) => setClaimTypeId(e.target.value)}
              >
                <option value="">— Pilih —</option>
                {types.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.limit_per_claim != null
                      ? ` (maks ${rupiah(t.limit_per_claim)}/pengajuan)`
                      : ""}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Nominal (Rp)" required>
              <input
                className={inputCls}
                type="number"
                min={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="1500000"
              />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Tanggal klaim" required>
                <input
                  className={inputCls}
                  type="date"
                  value={claimDate}
                  onChange={(e) => setClaimDate(e.target.value)}
                />
              </Field>
              <Field label="Dibayar via">
                <select
                  className={inputCls}
                  value={paidVia}
                  onChange={(e) => setPaidVia(e.target.value)}
                >
                  <option value="payroll">Payroll</option>
                  <option value="transfer">Transfer</option>
                </select>
              </Field>
            </div>
            <Field label="Deskripsi">
              <textarea
                className={inputCls}
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="cth. Biaya berobat RS …"
              />
            </Field>
            <Field
              label="Struk / bukti"
              required={selectedType?.requires_receipt ?? false}
              hint="Format: PDF, JPG, PNG, DOC, XLS (maks 10 MB)."
            >
              <input
                className={inputCls}
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx"
                onChange={(e) => setReceipt(e.target.files?.[0] ?? null)}
              />
            </Field>
          </div>
        </Modal>
      )}
    </div>
  );
}
