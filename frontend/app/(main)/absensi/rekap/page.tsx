"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  AttendanceSummary,
  Employment,
  Person,
} from "@/lib/types";
import { angka, namaBulan } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  Field,
  inputCls,
} from "@/components/ui";

// Nama bulan Bahasa Indonesia (input month native mengikuti locale browser,
// bisa tampil "October 2026", jadi pakai select manual).
const BULAN_ID = [
  "Januari",
  "Februari",
  "Maret",
  "April",
  "Mei",
  "Juni",
  "Juli",
  "Agustus",
  "September",
  "Oktober",
  "November",
  "Desember",
];

function MonthYearSelect({
  period,
  onChange,
}: {
  period: string;
  onChange: (period: string) => void;
}) {
  const [y, m] = period.split("-").map(Number);
  const years: number[] = [];
  const thisYear = new Date().getFullYear();
  for (let yy = thisYear - 5; yy <= thisYear + 1; yy++) years.push(yy);
  const set = (ny: number, nm: number) =>
    onChange(`${ny}-${String(nm).padStart(2, "0")}`);
  const selCls =
    "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900";
  return (
    <span className="flex items-center gap-2 text-sm text-slate-600">
      Periode
      <select
        aria-label="Bulan"
        className={selCls}
        value={m}
        onChange={(e) => set(y, Number(e.target.value))}
      >
        {BULAN_ID.map((nama, i) => (
          <option key={nama} value={i + 1}>
            {nama}
          </option>
        ))}
      </select>
      <select
        aria-label="Tahun"
        className={selCls}
        value={y}
        onChange={(e) => set(Number(e.target.value), m)}
      >
        {years.map((yy) => (
          <option key={yy} value={yy}>
            {yy}
          </option>
        ))}
      </select>
    </span>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-bold text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

function fmtMenit(mnt: number): string {
  const jam = Math.floor(mnt / 60);
  const sisa = mnt % 60;
  if (jam === 0) return `${angka(sisa)} mnt`;
  return `${angka(jam)} jam ${angka(sisa)} mnt`;
}

interface Option {
  employmentId: string;
  name: string;
}

export default function RekapAbsensiPage() {
  const [options, setOptions] = useState<Option[]>([]);
  const [employmentId, setEmploymentId] = useState("");
  const [period, setPeriod] = useState(() =>
    new Date().toISOString().slice(0, 7)
  );
  const [summary, setSummary] = useState<AttendanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rekapLoading, setRekapLoading] = useState(false);
  const [rekapError, setRekapError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [persons, emps] = await Promise.all([
          apiFetch<Person[]>("/persons"),
          apiFetch<Employment[]>("/employments"),
        ]);
        const personById = new Map(persons.map((p) => [p.id, p]));
        const opts = emps
          .filter((e) => e.status === "active")
          .map((e) => ({
            employmentId: e.id,
            name: personById.get(e.person_id)?.full_name ?? e.id.slice(0, 8),
          }))
          .sort((a, b) => a.name.localeCompare(b.name, "id"));
        setOptions(opts);
        setEmploymentId(opts[0]?.employmentId ?? "");
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Gagal memuat data karyawan."
        );
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!employmentId) return;
    (async () => {
      setRekapLoading(true);
      setRekapError(null);
      try {
        const s = await apiFetch<AttendanceSummary>(
          `/attendance/summary?employment_id=${employmentId}&period=${period}`
        );
        setSummary(s);
      } catch (err) {
        setRekapError(
          err instanceof ApiError ? err.message : "Gagal memuat rekap."
        );
        setSummary(null);
      } finally {
        setRekapLoading(false);
      }
    })();
  }, [employmentId, period]);

  const selectedName = useMemo(
    () => options.find((o) => o.employmentId === employmentId)?.name ?? "",
    [options, employmentId]
  );

  if (loading) return <Spinner label="Memuat data karyawan…" />;
  if (error) return <ErrorBox message={error} onRetry={() => location.reload()} />;

  return (
    <div>
      <PageHeader
        title="Rekap Absensi"
        subtitle={
          selectedName ? `${selectedName} · ${namaBulan(period)}` : namaBulan(period)
        }
        action={<MonthYearSelect period={period} onChange={setPeriod} />}
      />

      <Card title="Pilih karyawan">
        <div className="max-w-md">
          <Field label="Karyawan">
            <select
              value={employmentId}
              onChange={(e) => setEmploymentId(e.target.value)}
              className={inputCls}
            >
              {options.map((o) => (
                <option key={o.employmentId} value={o.employmentId}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>

      <div className="mt-4">
        {rekapLoading ? (
          <Spinner label="Memuat rekap…" />
        ) : rekapError ? (
          <ErrorBox message={rekapError} onRetry={() => location.reload()} />
        ) : summary ? (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Hadir" value={angka(summary.present)} hint="Hari" />
            <StatCard
              label="Terlambat"
              value={angka(summary.late)}
              hint={`Total ${angka(summary.total_late_minutes)} mnt`}
            />
            <StatCard label="Mangkir" value={angka(summary.absent)} hint="Hari" />
            <StatCard label="Cuti" value={angka(summary.leave)} hint="Hari" />
            <StatCard label="Libur" value={angka(summary.holiday)} hint="Hari" />
            <StatCard
              label="Total jam kerja"
              value={fmtMenit(summary.total_work_minutes)}
            />
          </div>
        ) : null}
        <p className="mt-3 text-xs text-slate-400">
          Hari kerja dihitung Senin–Jumat; hari tanpa record, cuti, atau libur
          dihitung sebagai mangkir.
        </p>
      </div>
    </div>
  );
}
