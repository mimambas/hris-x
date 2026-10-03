"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggal } from "@/lib/format";
import {
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  PageHeader,
  Spinner,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

interface InboxItem {
  kind: "cuti" | "lembur" | "klaim" | "pinjaman";
  id: string;
  requester_name: string;
  summary: string;
  stage: "L1" | "final";
  status: string;
  submitted_at: string | null;
}

interface InboxData {
  items: InboxItem[];
  counts: Record<string, number>;
}

interface Delegation {
  id: string;
  delegator_employment_id: string;
  delegator_name: string | null;
  delegate_employment_id: string;
  delegate_name: string | null;
  start_date: string;
  end_date: string;
  status: string;
  effective_now: boolean;
  note: string | null;
  created_at: string;
  direction: string;
}

interface Candidate {
  employment_id: string;
  person_name: string;
  job_title: string | null;
}

const KIND_META: Record<InboxItem["kind"], { label: string; icon: string }> = {
  cuti: { label: "Cuti", icon: "🌴" },
  lembur: { label: "Lembur", icon: "🌙" },
  klaim: { label: "Klaim", icon: "💸" },
  pinjaman: { label: "Pinjaman", icon: "🏦" },
};

// Aksi setujui per jenis & tahap — memakai endpoint modul masing-masing.
function approvePath(item: InboxItem): string {
  switch (item.kind) {
    case "cuti":
      return item.stage === "L1"
        ? `/leave/requests/${item.id}/approve-l1`
        : `/leave/requests/${item.id}/approve-l2`;
    case "lembur":
      return item.stage === "L1"
        ? `/overtime/requests/${item.id}/approve-l1`
        : `/overtime/requests/${item.id}/approve-l2`;
    case "klaim":
      return item.stage === "L1"
        ? `/claims/${item.id}/approve-l1`
        : `/claims/${item.id}/approve`;
    case "pinjaman":
      return `/loans/${item.id}/approve`;
  }
}

function rejectPath(item: InboxItem): string {
  switch (item.kind) {
    case "cuti":
      return `/leave/requests/${item.id}/reject`;
    case "lembur":
      return `/overtime/requests/${item.id}/reject`;
    case "klaim":
      return `/claims/${item.id}/reject`;
    case "pinjaman":
      return `/loans/${item.id}/reject`;
  }
}

export default function KotakMasukPage() {
  const [inbox, setInbox] = useState<InboxData | null>(null);
  const [delegations, setDelegations] = useState<Delegation[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<InboxItem | null>(null);
  const [rejecting, setRejecting] = useState<InboxItem | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  // Form delegasi baru.
  const [delegateId, setDelegateId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Delegation | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [ib, mine, cand] = await Promise.all([
        apiFetch<InboxData>("/inbox/approvals"),
        apiFetch<Delegation[]>("/delegations/mine").catch(() => []),
        apiFetch<Candidate[]>("/delegations/candidates").catch(() => []),
      ]);
      setInbox(ib);
      setDelegations(mine);
      setCandidates(cand);
      setSelected(new Set());
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Gagal memuat kotak masuk."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => inbox?.items ?? [], [inbox]);
  const given = delegations.filter((d) => d.direction === "diberikan");
  const received = delegations.filter((d) => d.direction === "diterima");

  async function act(item: InboxItem, approve: boolean, reason: string) {
    setBusyId(item.id);
    setActionError(null);
    try {
      await apiFetch(approve ? approvePath(item) : rejectPath(item), {
        method: "POST",
        body: JSON.stringify({ reason: reason || null }),
      });
      setNotice(
        approve
          ? `Pengajuan ${KIND_META[item.kind].label.toLowerCase()} ${item.requester_name} disetujui.`
          : `Pengajuan ${KIND_META[item.kind].label.toLowerCase()} ${item.requester_name} ditolak.`
      );
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Aksi gagal.");
    } finally {
      setBusyId(null);
    }
  }

  async function approveSelected() {
    const targets = items.filter((i) => selected.has(i.id));
    if (targets.length === 0) return;
    setBulkBusy(true);
    setActionError(null);
    let ok = 0;
    const failed: string[] = [];
    for (const item of targets) {
      try {
        await apiFetch(approvePath(item), {
          method: "POST",
          body: JSON.stringify({ reason: "Disetujui massal dari Kotak Masuk" }),
        });
        ok += 1;
      } catch {
        failed.push(`${item.requester_name} (${KIND_META[item.kind].label})`);
      }
    }
    setBulkBusy(false);
    setNotice(
      failed.length === 0
        ? `${ok} pengajuan disetujui.`
        : `${ok} disetujui; gagal: ${failed.join(", ")}.`
    );
    await load();
  }

  async function createDelegation() {
    if (!delegateId || !startDate || !endDate) {
      setActionError("Pilih penerima delegasi dan rentang tanggalnya.");
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      await apiFetch("/delegations", {
        method: "POST",
        body: JSON.stringify({
          delegate_employment_id: delegateId,
          start_date: startDate,
          end_date: endDate,
          note: note || null,
        }),
      });
      setNotice("Delegasi dibuat. Penerima dapat menyetujui pengajuan tim Anda selama periode delegasi.");
      setDelegateId("");
      setStartDate("");
      setEndDate("");
      setNote("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal membuat delegasi.");
    } finally {
      setCreating(false);
    }
  }

  async function revokeDelegation(d: Delegation) {
    setBusyId(d.id);
    setActionError(null);
    try {
      await apiFetch(`/delegations/${d.id}`, { method: "DELETE" });
      setNotice("Delegasi dicabut.");
      setRevoking(null);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mencabut delegasi.");
    } finally {
      setBusyId(null);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Kotak Masuk"
        subtitle="Semua pengajuan yang menunggu persetujuan Anda — cuti, lembur, klaim, dan pinjaman dalam satu antrean."
      />

      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {actionError && <ErrorBox message={actionError} />}

      <Card title={`Antrean persetujuan (${items.length})`}>
        {loading ? (
          <Spinner />
        ) : error ? (
          <ErrorBox message={error} />
        ) : items.length === 0 ? (
          <EmptyState message="Tidak ada pengajuan yang menunggu tindakan Anda. 🎉" />
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {Object.entries(inbox?.counts ?? {}).map(([kind, n]) => (
                <span
                  key={kind}
                  className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
                >
                  {KIND_META[kind as InboxItem["kind"]].icon}{" "}
                  {KIND_META[kind as InboxItem["kind"]].label}: {n}
                </span>
              ))}
              <span className="flex-1" />
              <button
                className={btnSmall}
                disabled={selected.size === 0 || bulkBusy}
                onClick={() => void approveSelected()}
              >
                {bulkBusy
                  ? "Memproses…"
                  : `Setujui terpilih (${selected.size})`}
              </button>
            </div>
            <ul className="divide-y divide-slate-100">
              {items.map((item) => (
                <li key={`${item.kind}-${item.id}`} className="flex items-center gap-3 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggleSelect(item.id)}
                    aria-label={`Pilih pengajuan ${item.requester_name}`}
                  />
                  <span className="text-xl">{KIND_META[item.kind].icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800">
                      {item.requester_name}
                      <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                        {item.stage === "L1" ? "Menunggu atasan" : "Menunggu HR"}
                      </span>
                    </p>
                    <p className="truncate text-xs text-slate-500">
                      {item.summary}
                      {item.submitted_at
                        ? ` · diajukan ${tanggal(item.submitted_at.slice(0, 10))}`
                        : ""}
                    </p>
                  </div>
                  <button
                    className={btnPrimary}
                    disabled={busyId === item.id}
                    onClick={() => setConfirming(item)}
                  >
                    Setujui
                  </button>
                  <button
                    className={btnSecondary}
                    disabled={busyId === item.id}
                    onClick={() => {
                      setRejectReason("");
                      setRejecting(item);
                    }}
                  >
                    Tolak
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Delegasi yang saya berikan">
          {given.length === 0 ? (
            <EmptyState message="Belum ada delegasi. Buat delegasi saat Anda cuti agar approval tim tetap berjalan." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {given.map((d) => (
                <li key={d.id} className="py-3 text-sm">
                  <p className="font-medium text-slate-800">
                    Ke {d.delegate_name ?? "—"}
                    {d.effective_now && (
                      <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                        Sedang berlaku
                      </span>
                    )}
                    {d.status === "dicabut" && (
                      <span className="ml-2 rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                        Dicabut
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">
                    {tanggal(d.start_date)} s.d. {tanggal(d.end_date)}
                    {d.note ? ` · ${d.note}` : ""}
                  </p>
                  {d.status === "aktif" && (
                    <button
                      className={btnSmall}
                      disabled={busyId === d.id}
                      onClick={() => setRevoking(d)}
                    >
                      Cabut delegasi
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Delegasi yang saya terima">
          {received.length === 0 ? (
            <EmptyState message="Tidak ada delegasi masuk. Bila atasan mendelegasikan, pengajuan timnya muncul di antrean Anda selama periode delegasi." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {received.map((d) => (
                <li key={d.id} className="py-3 text-sm">
                  <p className="font-medium text-slate-800">
                    Dari {d.delegator_name ?? "—"}
                    {d.effective_now && (
                      <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                        Sedang berlaku
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">
                    {tanggal(d.start_date)} s.d. {tanggal(d.end_date)}
                    {d.note ? ` · ${d.note}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Buat delegasi baru">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Penerima delegasi">
            <select
              className={inputCls}
              value={delegateId}
              onChange={(e) => setDelegateId(e.target.value)}
            >
              <option value="">— Pilih karyawan —</option>
              {candidates.map((c) => (
                <option key={c.employment_id} value={c.employment_id}>
                  {c.person_name}
                  {c.job_title ? ` (${c.job_title})` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Mulai">
            <input
              type="date"
              className={inputCls}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
          <Field label="Selesai (delegasi berakhir otomatis)">
            <input
              type="date"
              className={inputCls}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </Field>
          <Field label="Catatan (opsional)">
            <input
              className={inputCls}
              value={note}
              maxLength={255}
              placeholder="cth. Selama cuti tahunan"
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4">
          <button
            className={btnPrimary}
            disabled={creating}
            onClick={() => void createDelegation()}
          >
            {creating ? "Menyimpan…" : "Buat delegasi"}
          </button>
        </div>
      </Card>

      {confirming && (
        <Modal
          title="Setujui pengajuan?"
          onClose={() => setConfirming(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setConfirming(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === confirming.id}
                onClick={() => {
                  const item = confirming;
                  setConfirming(null);
                  void act(item, true, "");
                }}
              >
                Ya, setujui
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            {KIND_META[confirming.kind].label} — {confirming.requester_name}:{" "}
            {confirming.summary}
          </p>
        </Modal>
      )}

      {rejecting && (
        <Modal
          title="Tolak pengajuan?"
          onClose={() => setRejecting(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setRejecting(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === rejecting.id || rejectReason.trim() === ""}
                onClick={() => {
                  const item = rejecting;
                  setRejecting(null);
                  void act(item, false, rejectReason.trim());
                }}
              >
                Ya, tolak
              </button>
            </>
          }
        >
          <p className="mb-3 text-sm text-slate-600">
            {KIND_META[rejecting.kind].label} — {rejecting.requester_name}:{" "}
            {rejecting.summary}
          </p>
          <Field label="Alasan penolakan (wajib)">
            <input
              className={inputCls}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Alasan untuk pemohon"
            />
          </Field>
        </Modal>
      )}

      {revoking && (
        <Modal
          title="Cabut delegasi?"
          onClose={() => setRevoking(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setRevoking(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === revoking.id}
                onClick={() => void revokeDelegation(revoking)}
              >
                Ya, cabut
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            Delegasi ke {revoking.delegate_name ?? "—"} (
            {tanggal(revoking.start_date)} s.d. {tanggal(revoking.end_date)})
            akan berhenti berlaku sekarang.
          </p>
        </Modal>
      )}
    </div>
  );
}
