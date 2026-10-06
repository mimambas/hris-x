"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggal } from "@/lib/format";
import {
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  Spinner,
} from "@/components/ui";

interface Member {
  employment_id: string;
  person_name: string;
  status: string;
  check_in: string | null;
  late_minutes: number;
  leave_type_name: string | null;
  overtime_hours_today: number;
}

interface LeaveItem {
  employment_id: string;
  person_name: string;
  leave_type_name: string;
  start_date: string;
  end_date: string;
}

interface Dashboard {
  date: string;
  team_size: number;
  present: number;
  late: number;
  on_leave: number;
  absent: number;
  not_checked_in: number;
  overtime_today_count: number;
  overtime_hours_today: number;
  pending_approvals: number;
  members: Member[];
  on_leave_today: LeaveItem[];
  upcoming_leave: LeaveItem[];
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  hadir: { label: "Hadir", cls: "bg-emerald-100 text-emerald-800" },
  telat: { label: "Telat", cls: "bg-amber-100 text-amber-800" },
  cuti: { label: "Cuti", cls: "bg-sky-100 text-sky-800" },
  tidak_hadir: { label: "Tidak hadir", cls: "bg-rose-100 text-rose-700" },
  belum_absen: { label: "Belum absen", cls: "bg-slate-200 text-slate-600" },
};

function jam(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

export default function TimPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [noTeam, setNoTeam] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Dashboard>("/team/dashboard")
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) {
          setNoTeam(e.message);
        } else {
          setError(
            e instanceof ApiError ? e.message : "Gagal memuat dasbor tim."
          );
        }
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dasbor Tim"
        subtitle="Status tim Anda hari ini: kehadiran, keterlambatan, cuti, dan lembur yang berjalan."
      />

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : noTeam ? (
        <EmptyState message={noTeam} />
      ) : !data ? (
        <EmptyState message="Data tim tidak tersedia." />
      ) : (
        <>
          <p className="text-sm text-slate-500">
            {tanggal(data.date)} · {data.team_size} anggota tim langsung
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Hadir" value={String(data.present)} />
            <StatCard label="Telat" value={String(data.late)} />
            <StatCard label="Cuti" value={String(data.on_leave)} />
            <StatCard label="Belum absen" value={String(data.not_checked_in)} />
            <StatCard
              label="Lembur hari ini"
              value={String(data.overtime_today_count)}
              sub={`${data.overtime_hours_today} jam total`}
            />
            <StatCard
              label="Menunggu persetujuan"
              value={String(data.pending_approvals)}
              sub="cuti & lembur tim"
            />
          </div>
          {data.pending_approvals > 0 && (
            <p className="text-sm">
              Ada pengajuan tim yang menunggu keputusan Anda.{" "}
              <Link className="font-medium text-emerald-700 underline" href="/kotak-masuk">
                Buka Kotak Masuk →
              </Link>
            </p>
          )}

          <Card title="Status anggota hari ini">
            {data.members.length === 0 ? (
              <EmptyState message="Belum ada anggota tim." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400">
                      <th className="py-1 pr-2 font-medium">Nama</th>
                      <th className="px-2 py-1 font-medium">Status</th>
                      <th className="px-2 py-1 font-medium">Check-in</th>
                      <th className="px-2 py-1 font-medium">Telat</th>
                      <th className="px-2 py-1 font-medium">Lembur hari ini</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.members.map((m) => {
                      const meta = STATUS_META[m.status] ?? {
                        label: m.status,
                        cls: "bg-slate-200 text-slate-600",
                      };
                      return (
                        <tr key={m.employment_id} className="border-t border-slate-100">
                          <td className="py-2 pr-2 font-medium text-slate-800">
                            {m.person_name}
                          </td>
                          <td className="px-2 py-2">
                            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.cls}`}>
                              {meta.label}
                              {m.status === "cuti" && m.leave_type_name
                                ? ` · ${m.leave_type_name}`
                                : ""}
                            </span>
                          </td>
                          <td className="px-2 py-2 text-slate-600">
                            {m.check_in ? jam(m.check_in) : "—"}
                          </td>
                          <td className="px-2 py-2 text-slate-600">
                            {m.late_minutes > 0 ? `${m.late_minutes} mnt` : "—"}
                          </td>
                          <td className="px-2 py-2 text-slate-600">
                            {m.overtime_hours_today > 0
                              ? `${m.overtime_hours_today} jam`
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title={`Sedang cuti hari ini (${data.on_leave_today.length})`}>
              {data.on_leave_today.length === 0 ? (
                <EmptyState message="Tidak ada anggota tim yang cuti hari ini." />
              ) : (
                <ul className="divide-y divide-slate-100">
                  {data.on_leave_today.map((l) => (
                    <li key={l.employment_id} className="py-2 text-sm">
                      <span className="font-medium text-slate-800">{l.person_name}</span>{" "}
                      <span className="text-slate-500">
                        · {l.leave_type_name} · {tanggal(l.start_date)} s.d.{" "}
                        {tanggal(l.end_date)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title={`Cuti 7 hari ke depan (${data.upcoming_leave.length})`}>
              {data.upcoming_leave.length === 0 ? (
                <EmptyState message="Tidak ada cuti tim dalam 7 hari ke depan." />
              ) : (
                <ul className="divide-y divide-slate-100">
                  {data.upcoming_leave.map((l) => (
                    <li key={`${l.employment_id}-${l.start_date}`} className="py-2 text-sm">
                      <span className="font-medium text-slate-800">{l.person_name}</span>{" "}
                      <span className="text-slate-500">
                        · {l.leave_type_name} · {tanggal(l.start_date)} s.d.{" "}
                        {tanggal(l.end_date)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
