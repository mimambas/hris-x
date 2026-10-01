"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch, ApiError } from "@/lib/api";
import type { HeadcountResponse, TurnoverResponse } from "@/lib/types";
import { angka, persen, tanggal, namaBulan, labelBulanSingkat } from "@/lib/format";
import { Card, PageHeader, Spinner, ErrorBox } from "@/components/ui";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-bold text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const [asOf] = useState(todayISO());
  const [period, setPeriod] = useState(() => todayISO().slice(0, 7));
  const [headcount, setHeadcount] = useState<HeadcountResponse | null>(null);
  const [turnover, setTurnover] = useState<TurnoverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [hc, to] = await Promise.all([
        apiFetch<HeadcountResponse>(`/dashboard/headcount?as_of=${asOf}`),
        apiFetch<TurnoverResponse>(`/dashboard/turnover?period=${period}`),
      ]);
      setHeadcount(hc);
      setTurnover(to);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat dasbor.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  const unitData = useMemo(() => {
    if (!headcount) return [];
    return Object.entries(headcount.by_org_unit)
      .map(([name, total]) => ({ name, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 12);
  }, [headcount]);

  const trendData = useMemo(() => {
    if (!turnover) return [];
    return turnover.trend_12_months.map((t) => ({
      ...t,
      label: labelBulanSingkat(t.period),
    }));
  }, [turnover]);

  const turnoverUnitData = useMemo(() => {
    if (!turnover) return [];
    return Object.entries(turnover.by_org_unit)
      .map(([name, total]) => ({ name, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 12);
  }, [turnover]);

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Dasbor"
        subtitle={`Per ${tanggal(headcount?.as_of ?? asOf)}`}
        action={
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Periode turnover
            <input
              type="month"
              value={period}
              onChange={(e) => e.target.value && setPeriod(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total karyawan"
          value={angka(headcount?.total)}
          hint="Aktif per tanggal laporan"
        />
        <StatCard
          label="Karyawan baru bulan ini"
          value={angka(headcount?.new_this_month)}
        />
        <StatCard
          label="Karyawan keluar bulan ini"
          value={angka(headcount?.left_this_month)}
        />
        <StatCard
          label={`Turnover ${namaBulan(turnover?.period ?? period)}`}
          value={persen(turnover?.rate_pct)}
          hint={`${angka(turnover?.terminated)} keluar dari rata-rata ${angka(
            Math.round(turnover?.avg_headcount ?? 0)
          )} karyawan`}
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Tren turnover 12 bulan" subtitle="Persentase per bulan">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData} margin={{ left: -10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} />
                <Tooltip
                  formatter={(v: number) => [`${v}%`, "Turnover"]}
                  labelFormatter={(_, payload) =>
                    payload?.[0]?.payload?.period
                      ? namaBulan(String(payload[0].payload.period))
                      : ""
                  }
                />
                <Line
                  type="monotone"
                  dataKey="rate_pct"
                  stroke="#2563eb"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Karyawan per unit" subtitle="Breakdown headcount aktif">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={unitData} layout="vertical" margin={{ left: 20, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={130}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip formatter={(v: number) => [angka(v), "Karyawan"]} />
                <Bar dataKey="total" fill="#2563eb" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {turnoverUnitData.length > 0 && (
        <div className="mt-4">
          <Card
            title="Karyawan keluar per unit"
            subtitle={`Periode ${namaBulan(turnover?.period ?? period)}`}
          >
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={turnoverUnitData} margin={{ left: -10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} dy={10} height={60} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip formatter={(v: number) => [angka(v), "Keluar"]} />
                  <Bar dataKey="total" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
