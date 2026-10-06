"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggal, localISO } from "@/lib/format";
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

interface RosterDay {
  date: string;
  shift_code: string | null;
  shift_name: string | null;
  start_time: string | null;
  end_time: string | null;
  is_overnight: boolean;
}

interface RosterMember {
  employment_id: string;
  person_name: string;
  days: RosterDay[];
}

interface Roster {
  start_date: string;
  end_date: string;
  members: RosterMember[];
}

interface Swap {
  id: string;
  requester_employment_id: string;
  requester_name: string | null;
  partner_employment_id: string;
  partner_name: string | null;
  swap_date: string;
  requester_shift_name: string | null;
  partner_shift_name: string | null;
  reason: string | null;
  warnings: string[];
  status: string;
  decision_reason: string | null;
  created_at: string;
}

interface Candidate {
  employment_id: string;
  person_name: string;
  shift_name: string | null;
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  menunggu_partner: { label: "Menunggu persetujuan partner", cls: "bg-violet-100 text-violet-800" },
  menunggu_atasan: { label: "Menunggu persetujuan atasan", cls: "bg-amber-100 text-amber-800" },
  disetujui: { label: "Disetujui & diterapkan", cls: "bg-emerald-100 text-emerald-800" },
  ditolak: { label: "Ditolak", cls: "bg-rose-100 text-rose-700" },
  dibatalkan: { label: "Dibatalkan", cls: "bg-slate-200 text-slate-600" },
};

const DAY_ABBR = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];

function mondayOf(d: Date): Date {
  const x = new Date(d);
  const dow = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - dow);
  x.setHours(0, 0, 0, 0);
  return x;
}

function iso(d: Date): string {
  return localISO(d);
}

export default function RosterPage() {
  const [myEmploymentId, setMyEmploymentId] = useState<string | null>(null);

  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(new Date()));
  const [teamRoster, setTeamRoster] = useState<Roster | null>(null);
  const [myRoster, setMyRoster] = useState<Roster | null>(null);
  const [mine, setMine] = useState<Swap[]>([]);
  const [approvals, setApprovals] = useState<Swap[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Form ajukan tukar.
  const [swapDate, setSwapDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return iso(d);
  });
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [partnerId, setPartnerId] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Keputusan.
  const [deciding, setDeciding] = useState<{
    swap: Swap;
    kind: "partner" | "manager" | "cancel";
    approve: boolean;
  } | null>(null);
  const [decisionReason, setDecisionReason] = useState("");

  const weekEnd = useMemo(() => {
    const e = new Date(weekStart);
    e.setDate(e.getDate() + 6);
    return e;
  }, [weekStart]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const qs = `?start=${iso(weekStart)}&end=${iso(weekEnd)}`;
      const [me, swaps, appr] = await Promise.all([
        apiFetch<Roster>(`/roster/me${qs}`),
        apiFetch<Swap[]>("/shift-swaps/mine").catch(() => []),
        apiFetch<Swap[]>("/shift-swaps/approvals").catch(() => []),
      ]);
      setMyRoster(me);
      setMyEmploymentId(me.members[0]?.employment_id ?? null);
      setMine(swaps);
      setApprovals(appr);
      const team = await apiFetch<Roster>(`/roster/team${qs}`).catch(
        () => null
      );
      setTeamRoster(team);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat roster.");
    } finally {
      setLoading(false);
    }
  }, [weekStart, weekEnd]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!swapDate) return;
    apiFetch<Candidate[]>(`/shift-swaps/candidates?date=${swapDate}`)
      .then((rows) => {
        setCandidates(rows);
        setPartnerId((prev) =>
          rows.some((r) => r.employment_id === prev)
            ? prev
            : (rows[0]?.employment_id ?? "")
        );
      })
      .catch(() => setCandidates([]));
  }, [swapDate]);

  async function submitSwap() {
    if (!partnerId) {
      setActionError("Pilih partner tukar dulu.");
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const created = await apiFetch<Swap>("/shift-swaps", {
        method: "POST",
        body: JSON.stringify({
          partner_employment_id: partnerId,
          swap_date: swapDate,
          reason: reason.trim() || null,
        }),
      });
      setNotice(
        created.warnings.length > 0
          ? `Permintaan terkirim dengan ${created.warnings.length} peringatan konflik. Menunggu persetujuan partner.`
          : "Permintaan tukar terkirim. Menunggu persetujuan partner."
      );
      setReason("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengajukan.");
    } finally {
      setSubmitting(false);
    }
  }

  async function decide() {
    if (!deciding) return;
    const { swap, kind, approve } = deciding;
    if (!approve && kind !== "cancel" && !decisionReason.trim()) {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    try {
      const path =
        kind === "cancel"
          ? `/shift-swaps/${swap.id}/cancel`
          : kind === "partner"
            ? `/shift-swaps/${swap.id}/partner-decision`
            : `/shift-swaps/${swap.id}/manager-decision`;
      await apiFetch(path, {
        method: "POST",
        body:
          kind === "cancel"
            ? undefined
            : JSON.stringify({
                approve,
                reason: decisionReason.trim() || null,
              }),
      });
      setNotice(
        kind === "cancel"
          ? "Permintaan dibatalkan."
          : approve
            ? "Keputusan tersimpan."
            : "Permintaan ditolak."
      );
      setDeciding(null);
      setDecisionReason("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal memproses.");
    }
  }

  function rosterTable(roster: Roster) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="py-1 pr-2 font-medium">Nama</th>
              {roster.members[0]?.days.map((d) => (
                <th key={d.date} className="px-1 py-1 text-center font-medium">
                  {DAY_ABBR[new Date(`${d.date}T12:00:00`).getDay()]}
                  <span className="block font-normal">
                    {tanggal(d.date).split(" ")[0]}/
                    {tanggal(d.date).split(" ")[1] ?? ""}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {roster.members.map((m) => (
              <tr key={m.employment_id} className="border-t border-slate-100">
                <td className="py-2 pr-2 font-medium whitespace-nowrap text-slate-800">
                  {m.person_name}
                </td>
                {m.days.map((d) => (
                  <td key={d.date} className="px-1 py-2 text-center">
                    {d.shift_name ? (
                      <span className="inline-block rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800">
                        {d.shift_name}
                        <span className="block font-normal text-emerald-600">
                          {d.start_time}–{d.end_time}
                          {d.is_overnight ? " 🌙" : ""}
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function swapRow(s: Swap) {
    const meta = STATUS_META[s.status] ?? STATUS_META.menunggu_partner;
    const iAmRequester = myEmploymentId === s.requester_employment_id;
    const iAmPartner = myEmploymentId === s.partner_employment_id;
    return (
      <li key={s.id} className="py-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-sm font-medium text-slate-800">
            {tanggal(s.swap_date)} · {s.requester_name ?? "?"} (
            {s.requester_shift_name ?? "?"}) ↔ {s.partner_name ?? "?"} (
            {s.partner_shift_name ?? "?"})
          </p>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.cls}`}>
            {meta.label}
          </span>
        </div>
        {s.reason && <p className="text-sm text-slate-500">{s.reason}</p>}
        {s.warnings.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {s.warnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-700">
                ⚠️ {w}
              </li>
            ))}
          </ul>
        )}
        {s.status === "ditolak" && s.decision_reason && (
          <p className="text-xs text-rose-600">Alasan: {s.decision_reason}</p>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          {iAmPartner && s.status === "menunggu_partner" && (
            <>
              <button
                className={btnPrimary}
                onClick={() =>
                  setDeciding({ swap: s, kind: "partner", approve: true })
                }
              >
                Setujui tukar
              </button>
              <button
                className={btnSecondary}
                onClick={() => {
                  setDecisionReason("");
                  setDeciding({ swap: s, kind: "partner", approve: false });
                }}
              >
                Tolak
              </button>
            </>
          )}
          {iAmRequester &&
            (s.status === "menunggu_partner" ||
              s.status === "menunggu_atasan") && (
              <button
                className={btnSmall}
                onClick={() =>
                  setDeciding({ swap: s, kind: "cancel", approve: false })
                }
              >
                Batalkan permintaan
              </button>
            )}
        </div>
      </li>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Roster & Tukar Shift"
        subtitle="Jadwal shift mingguan Anda dan tim, plus tukar shift satu hari dengan persetujuan partner dan atasan."
      />

      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {actionError && <ErrorBox message={actionError} />}

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className={btnSecondary}
              onClick={() => {
                const d = new Date(weekStart);
                d.setDate(d.getDate() - 7);
                setWeekStart(d);
              }}
            >
              ← Minggu sebelumnya
            </button>
            <p className="flex-1 text-center text-sm font-medium text-slate-700">
              {tanggal(iso(weekStart))} s.d. {tanggal(iso(weekEnd))}
            </p>
            <button
              className={btnSecondary}
              onClick={() => {
                const d = new Date(weekStart);
                d.setDate(d.getDate() + 7);
                setWeekStart(d);
              }}
            >
              Minggu berikutnya →
            </button>
          </div>

          {teamRoster ? (
            <Card title="Roster tim minggu ini">{rosterTable(teamRoster)}</Card>
          ) : (
            myRoster && (
              <Card title="Jadwal saya minggu ini">{rosterTable(myRoster)}</Card>
            )
          )}

          <Card title="Ajukan tukar shift">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Tanggal tukar">
                <input
                  className={inputCls}
                  type="date"
                  value={swapDate}
                  onChange={(e) => setSwapDate(e.target.value)}
                />
              </Field>
              <Field label="Partner tukar (shift pada tanggal itu)">
                <select
                  className={inputCls}
                  value={partnerId}
                  onChange={(e) => setPartnerId(e.target.value)}
                >
                  {candidates.length === 0 && (
                    <option value="">Tidak ada kandidat</option>
                  )}
                  {candidates.map((c) => (
                    <option key={c.employment_id} value={c.employment_id}>
                      {c.person_name}
                      {c.shift_name ? ` — ${c.shift_name}` : " — tanpa shift"}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Alasan (opsional)">
                <input
                  className={inputCls}
                  maxLength={500}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="cth. Keperluan keluarga pagi hari"
                />
              </Field>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Tukar berlaku satu hari pada tanggal yang sama. Sistem akan
              memperingatkan bila hasil tukar membuat istirahat kurang dari
              8 jam atau bentrok dengan lembur/cuti yang sudah disetujui.
            </p>
            <div className="mt-3">
              <button
                className={btnPrimary}
                disabled={submitting || !partnerId}
                onClick={() => void submitSwap()}
              >
                {submitting ? "Mengirim…" : "Kirim permintaan tukar"}
              </button>
            </div>
          </Card>

          <Card title={`Tukar shift saya (${mine.length})`}>
            {mine.length === 0 ? (
              <EmptyState message="Belum ada permintaan tukar shift." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {mine.map(swapRow)}
              </ul>
            )}
          </Card>

          {approvals.length > 0 && (
            <Card title={`Menunggu persetujuan saya sebagai atasan (${approvals.length})`}>
              <ul className="divide-y divide-slate-100">
                {approvals.map((s) => (
                  <li key={s.id} className="py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="flex-1 text-sm font-medium text-slate-800">
                        {tanggal(s.swap_date)} · {s.requester_name ?? "?"} (
                        {s.requester_shift_name ?? "?"}) ↔{" "}
                        {s.partner_name ?? "?"} ({s.partner_shift_name ?? "?"})
                      </p>
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                        Menunggu persetujuan atasan
                      </span>
                    </div>
                    {s.warnings.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {s.warnings.map((w, i) => (
                          <li key={i} className="text-xs text-amber-700">
                            ⚠️ {w}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        className={btnPrimary}
                        onClick={() =>
                          setDeciding({ swap: s, kind: "manager", approve: true })
                        }
                      >
                        Setujui & terapkan
                      </button>
                      <button
                        className={btnSecondary}
                        onClick={() => {
                          setDecisionReason("");
                          setDeciding({ swap: s, kind: "manager", approve: false });
                        }}
                      >
                        Tolak
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      {deciding && (
        <Modal
          title={
            deciding.kind === "cancel"
              ? "Batalkan permintaan tukar?"
              : deciding.approve
                ? "Setujui tukar shift?"
                : "Tolak tukar shift?"
          }
          onClose={() => setDeciding(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setDeciding(null)}>
                Kembali
              </button>
              <button className={btnPrimary} onClick={() => void decide()}>
                {deciding.kind === "cancel"
                  ? "Ya, batalkan"
                  : deciding.approve
                    ? "Ya, setujui"
                    : "Ya, tolak"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              {deciding.swap.requester_name} ({deciding.swap.requester_shift_name})
              ↔ {deciding.swap.partner_name} ({deciding.swap.partner_shift_name})
              pada {tanggal(deciding.swap.swap_date)}.
              {deciding.kind === "manager" &&
                deciding.approve &&
                " Jadwal kedua pihak pada tanggal itu akan ditukar dan diterapkan."}
            </p>
            {deciding.swap.warnings.length > 0 && (
              <ul className="space-y-0.5">
                {deciding.swap.warnings.map((w, i) => (
                  <li key={i} className="text-xs text-amber-700">
                    ⚠️ {w}
                  </li>
                ))}
              </ul>
            )}
            {!deciding.approve && deciding.kind !== "cancel" && (
              <Field label="Alasan penolakan (wajib)">
                <input
                  className={inputCls}
                  value={decisionReason}
                  onChange={(e) => setDecisionReason(e.target.value)}
                  placeholder="Alasan untuk karyawan"
                />
              </Field>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
