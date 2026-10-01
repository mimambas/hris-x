"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError, apiDownload } from "@/lib/api";
import type { PayrollRun, PayrollLine } from "@/lib/types";
import { rupiah, namaBulan } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  RunStatusChip,
  inputCls,
  btnSmall,
} from "@/components/ui";

export default function SlipPage() {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [runId, setRunId] = useState("");
  const [lines, setLines] = useState<PayrollLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [linesLoading, setLinesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linesError, setLinesError] = useState<string | null>(null);
  const [dlBusy, setDlBusy] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await apiFetch<PayrollRun[]>("/payroll/runs");
        setRuns(data);
        if (data.length > 0) setRunId(data[0].id);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Gagal memuat daftar periode payroll.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (!runId) return;
    async function loadLines() {
      setLinesLoading(true);
      setLinesError(null);
      try {
        const data = await apiFetch<PayrollLine[]>(`/payroll/runs/${runId}/lines`);
        setLines(data);
      } catch (err) {
        setLinesError(err instanceof ApiError ? err.message : "Gagal memuat daftar slip.");
      } finally {
        setLinesLoading(false);
      }
    }
    loadLines();
  }, [runId]);

  const run = runs.find((r) => r.id === runId);

  async function download(line: PayrollLine) {
    setDlBusy(line.id);
    try {
      await apiDownload(
        `/payroll/runs/${runId}/payslip/${line.employment_id}.pdf`,
        `slip-${run?.period ?? "gaji"}-${line.nik}.pdf`
      );
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Gagal mengunduh slip.");
    } finally {
      setDlBusy(null);
    }
  }

  if (loading) return <Spinner label="Memuat periode payroll…" />;
  if (error) return <ErrorBox message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <PageHeader
        title="Slip gaji"
        subtitle="Unduh slip gaji karyawan per periode payroll"
      />

      <Card title="Pilih periode">
        {runs.length === 0 ? (
          <EmptyState message="Belum ada periode payroll." />
        ) : (
          <div className="flex flex-wrap items-center gap-4">
            <select
              className={`${inputCls} max-w-xs`}
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {namaBulan(r.period)} · {r.headcount} karyawan
                </option>
              ))}
            </select>
            {run && <RunStatusChip status={run.status} />}
            {run?.totals && typeof run.totals.take_home_pay === "number" && (
              <p className="text-sm text-slate-600">
                Total take-home pay:{" "}
                <span className="font-semibold text-slate-900">
                  {rupiah(run.totals.take_home_pay as number)}
                </span>
              </p>
            )}
          </div>
        )}
      </Card>

      {runId && (
        <div className="mt-4">
          <Card title={`Daftar slip — ${namaBulan(run?.period ?? "")}`}>
            {linesLoading && <Spinner label="Memuat daftar slip…" />}
            {linesError && <ErrorBox message={linesError} />}
            {!linesLoading && !linesError && (
              lines.length === 0 ? (
                <EmptyState message="Tidak ada slip pada periode ini." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-200 text-sm">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium text-slate-600">Nama</th>
                        <th className="px-4 py-3 text-left font-medium text-slate-600">NIK</th>
                        <th className="px-4 py-3 text-right font-medium text-slate-600">Bruto</th>
                        <th className="px-4 py-3 text-right font-medium text-slate-600">Potongan</th>
                        <th className="px-4 py-3 text-right font-medium text-slate-600">PPh 21</th>
                        <th className="px-4 py-3 text-right font-medium text-slate-600">Take-home</th>
                        <th className="px-4 py-3 text-left font-medium text-slate-600">Aksi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {lines.map((l) => (
                        <tr key={l.id} className="hover:bg-slate-50">
                          <td className="px-4 py-3 font-medium text-slate-900">{l.person_name}</td>
                          <td className="px-4 py-3 font-mono text-xs text-slate-600">{l.nik}</td>
                          <td className="px-4 py-3 text-right text-slate-600">{rupiah(l.gross)}</td>
                          <td className="px-4 py-3 text-right text-slate-600">{rupiah(l.total_deductions)}</td>
                          <td className="px-4 py-3 text-right text-slate-600">{rupiah(l.pph21)}</td>
                          <td className="px-4 py-3 text-right font-semibold text-slate-900">
                            {rupiah(l.take_home_pay)}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => download(l)}
                              disabled={dlBusy === l.id}
                              className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                            >
                              {dlBusy === l.id ? "Mengunduh…" : "Unduh PDF"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
