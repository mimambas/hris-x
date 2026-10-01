"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  AttendanceRecord,
  Employment,
  Person,
} from "@/lib/types";
import { tanggal, tanggalWaktu, angka } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  Field,
  inputCls,
  btnPrimary,
  btnSecondary,
  Modal,
} from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  present: "Hadir",
  late: "Terlambat",
  absent: "Mangkir",
  leave: "Cuti",
  holiday: "Libur",
};

const STATUS_CLS: Record<string, string> = {
  present: "bg-emerald-100 text-emerald-800",
  late: "bg-amber-100 text-amber-800",
  absent: "bg-red-100 text-red-800",
  leave: "bg-blue-100 text-blue-800",
  holiday: "bg-slate-200 text-slate-700",
};

function AttendanceChip({ status }: { status: string }) {
  const cls = STATUS_CLS[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function jam(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

interface Row {
  employmentId: string;
  name: string;
  record: AttendanceRecord | null;
}

export default function AbsensiPage() {
  const [date, setDate] = useState(todayISO());
  const [statusFilter, setStatusFilter] = useState("semua");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [myEmploymentId, setMyEmploymentId] = useState("");
  const [myRecord, setMyRecord] = useState<AttendanceRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [teamForbidden, setTeamForbidden] = useState(false);
  const [confirm, setConfirm] = useState<"in" | "out" | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setTeamForbidden(false);
    setNotice(null);
    try {
      const [me, persons, emps] = await Promise.all([
        apiFetch<{ email: string }>("/me"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      const personById = new Map(persons.map((p) => [p.id, p]));
      const active = emps.filter((e) => e.status === "active");
      // Employment milik user (untuk check-in/out sendiri).
      const mePerson = persons.find(
        (p) => (p.email ?? "").toLowerCase() === me.email.toLowerCase()
      );
      const mine = active.find(
        (e) => mePerson && e.person_id === mePerson.id
      );
      setMyEmploymentId(mine?.id ?? "");

      const results = await Promise.allSettled(
        active.map(async (e): Promise<Row> => {
          const recs = await apiFetch<AttendanceRecord[]>(
            `/attendance/records?employment_id=${e.id}&date_from=${date}&date_to=${date}`
          );
          return {
            employmentId: e.id,
            name: personById.get(e.person_id)?.full_name ?? e.id.slice(0, 8),
            record: recs[0] ?? null,
          };
        })
      );
      const ok: Row[] = [];
      let forbidden = false;
      for (const r of results) {
        if (r.status === "fulfilled") {
          ok.push(r.value);
        } else if (r.reason instanceof ApiError && r.reason.status === 403) {
          forbidden = true;
        }
      }
      ok.sort((a, b) => a.name.localeCompare(b.name, "id"));
      setRows(ok);
      setTeamForbidden(forbidden && ok.length === 0);
      if (mine) {
        const mineRow = ok.find((r) => r.employmentId === mine.id);
        setMyRecord(mineRow?.record ?? null);
      } else {
        setMyRecord(null);
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal memuat data absensi."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (
          statusFilter !== "semua" &&
          (r.record?.status ?? "absent") !== statusFilter
        )
          return false;
        if (
          query &&
          !r.name.toLowerCase().includes(query.trim().toLowerCase())
        )
          return false;
        return true;
      }),
    [rows, statusFilter, query]
  );

  async function doCheck(kind: "in" | "out") {
    if (!myEmploymentId) return;
    setBusy(true);
    setNotice(null);
    try {
      const rec = await apiFetch<AttendanceRecord>(
        `/attendance/check-${kind}`,
        {
          method: "POST",
          body: JSON.stringify({
            employment_id: myEmploymentId,
            source: "web",
          }),
        }
      );
      setMyRecord(rec);
      setNotice(
        kind === "in"
          ? `Check-in tercatat pukul ${jam(rec.check_in)}.`
          : `Check-out tercatat pukul ${jam(rec.check_out)}.`
      );
      await load();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Gagal mencatat.");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  if (loading) return <Spinner label="Memuat data absensi…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Absensi"
        subtitle={`Kehadiran tanggal ${tanggal(date)}`}
        action={
          <div className="flex gap-2">
            <Link href="/absensi/rekap" className={btnSecondary}>
              Rekap periode
            </Link>
            <Link href="/absensi/koreksi" className={btnSecondary}>
              Koreksi kehadiran
            </Link>
          </div>
        }
      />

      {notice && (
        <div className="mb-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-emerald-200">
          {notice}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Absensi saya hari ini">
          {myEmploymentId ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">Status</span>
                <AttendanceChip status={myRecord?.status ?? "absent"} />
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">Jam masuk</span>
                <span className="font-medium">{jam(myRecord?.check_in ?? null)}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500">Jam keluar</span>
                <span className="font-medium">{jam(myRecord?.check_out ?? null)}</span>
              </div>
              {myRecord && myRecord.late_minutes > 0 && (
                <p className="text-sm text-amber-700">
                  Terlambat {angka(myRecord.late_minutes)} menit.
                </p>
              )}
              <div className="flex gap-2 pt-1">
                <button
                  className={btnPrimary}
                  disabled={busy || !!myRecord?.check_in}
                  onClick={() => setConfirm("in")}
                >
                  Check-in
                </button>
                <button
                  className={btnSecondary}
                  disabled={busy || !myRecord?.check_in || !!myRecord?.check_out}
                  onClick={() => setConfirm("out")}
                >
                  Check-out
                </button>
              </div>
              {!myRecord?.check_in && (
                <p className="text-xs text-slate-400">
                  Anda belum check-in hari ini.
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              Tidak ditemukan data kepegawaian aktif untuk akun ini.
            </p>
          )}
        </Card>

        <div className="lg:col-span-2">
          <Card
            title="Kehadiran karyawan"
            subtitle={`${angka(filtered.length)} dari ${angka(rows.length)} karyawan`}
          >
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Tanggal">
                <input
                  type="date"
                  value={date}
                  max={todayISO()}
                  onChange={(e) => e.target.value && setDate(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Status">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className={inputCls}
                >
                  <option value="semua">Semua status</option>
                  <option value="present">Hadir</option>
                  <option value="late">Terlambat</option>
                  <option value="absent">Mangkir</option>
                  <option value="leave">Cuti</option>
                  <option value="holiday">Libur</option>
                </select>
              </Field>
              <Field label="Cari nama">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Nama karyawan…"
                  className={inputCls}
                />
              </Field>
            </div>

            {teamForbidden ? (
              <p className="text-sm text-slate-500">
                Anda tidak memiliki izin melihat absensi karyawan lain. Data di
                atas hanya menampilkan absensi Anda sendiri.
              </p>
            ) : filtered.length === 0 ? (
              <EmptyState message="Tidak ada data kehadiran pada tanggal ini." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
                      <th className="py-2 pr-3 font-medium">Nama</th>
                      <th className="py-2 pr-3 font-medium">Masuk</th>
                      <th className="py-2 pr-3 font-medium">Keluar</th>
                      <th className="py-2 pr-3 font-medium">Status</th>
                      <th className="py-2 font-medium">Keterlambatan</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r) => (
                      <tr
                        key={r.employmentId}
                        className="border-b border-slate-100 last:border-0"
                      >
                        <td className="py-2 pr-3 font-medium text-slate-900">
                          {r.name}
                        </td>
                        <td className="py-2 pr-3 text-slate-600">
                          {r.record ? jam(r.record.check_in) : "-"}
                        </td>
                        <td className="py-2 pr-3 text-slate-600">
                          {r.record ? jam(r.record.check_out) : "-"}
                        </td>
                        <td className="py-2 pr-3">
                          <AttendanceChip status={r.record?.status ?? "absent"} />
                        </td>
                        <td className="py-2 text-slate-600">
                          {r.record && r.record.late_minutes > 0
                            ? `${angka(r.record.late_minutes)} mnt`
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-3 text-xs text-slate-400">
              Karyawan tanpa record pada hari kerja dihitung sebagai mangkir
              oleh sistem.
            </p>
          </Card>
        </div>
      </div>

      {confirm && (
        <Modal
          title={confirm === "in" ? "Check-in" : "Check-out"}
          onClose={() => !busy && setConfirm(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                disabled={busy}
                onClick={() => setConfirm(null)}
              >
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busy}
                onClick={() => doCheck(confirm)}
              >
                {busy ? "Menyimpan…" : "Ya, catat"}
              </button>
            </>
          }
        >
          <p>
            {confirm === "in"
              ? "Catat jam masuk sekarang sebagai check-in Anda hari ini?"
              : "Catat jam keluar sekarang sebagai check-out Anda hari ini?"}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            Waktu pencatatan: {tanggalWaktu(new Date().toISOString())}
          </p>
        </Modal>
      )}
    </div>
  );
}
