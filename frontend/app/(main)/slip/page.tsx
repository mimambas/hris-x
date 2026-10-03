"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError, apiDownload } from "@/lib/api";
import type { PayrollRun, PayrollLine } from "@/lib/types";
import { rupiah, namaBulan } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  Field,
  Modal,
  RunStatusChip,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

interface MySlip {
  run_id: string;
  period: string;
  employment_id: string;
  person_name: string;
  nik: string;
  take_home_pay: number;
}

interface PinStatus {
  pin_set: boolean;
  locked: boolean;
  employment_id: string | null;
}

interface DownloadTarget {
  runId: string;
  employmentId: string;
  period: string;
  nik: string;
}

type PinMode = "buat" | "masuk" | "ganti";

const PIN_ERROR_TEXT: Record<string, string> = {
  PIN_SALAH: "PIN salah. Periksa kembali PIN Anda.",
  PIN_TERKUNCI:
    "PIN terkunci sementara karena terlalu banyak percobaan salah. Coba lagi dalam 15 menit, atau minta HR mereset PIN Anda.",
  PIN_BELUM_DIATUR: "Anda belum mengatur PIN slip. Buat PIN dulu.",
};

export default function SlipPage() {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [canViewAll, setCanViewAll] = useState(true);
  const [runId, setRunId] = useState("");
  const [lines, setLines] = useState<PayrollLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [linesLoading, setLinesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linesError, setLinesError] = useState<string | null>(null);
  const [dlBusy, setDlBusy] = useState<string | null>(null);

  const [pinStatus, setPinStatus] = useState<PinStatus | null>(null);
  const [mySlips, setMySlips] = useState<MySlip[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  // Modal PIN.
  const [pinMode, setPinMode] = useState<PinMode | null>(null);
  const [pinTarget, setPinTarget] = useState<DownloadTarget | null>(null);
  const [pinValue, setPinValue] = useState("");
  const [pinConfirm, setPinConfirm] = useState("");
  const [pinNew, setPinNew] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [pinBusy, setPinBusy] = useState(false);

  const loadSelf = useCallback(async () => {
    const [st, mine] = await Promise.all([
      apiFetch<PinStatus>("/payslip-pin/status").catch(() => null),
      apiFetch<MySlip[]>("/payroll/my-payslips").catch(() => []),
    ]);
    setPinStatus(st);
    setMySlips(mine);
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await apiFetch<PayrollRun[]>("/payroll/runs");
        setRuns(data);
        setCanViewAll(true);
        if (data.length > 0) setRunId(data[0].id);
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) {
          // Karyawan biasa: hanya bagian slip sendiri yang tampil.
          setCanViewAll(false);
          setRuns([]);
        } else {
          setError(
            err instanceof ApiError
              ? err.message
              : "Gagal memuat daftar periode payroll."
          );
        }
      } finally {
        setLoading(false);
      }
      void loadSelf();
    }
    void load();
  }, [loadSelf]);

  useEffect(() => {
    if (!runId) return;
    async function loadLines() {
      setLinesLoading(true);
      setLinesError(null);
      try {
        const data = await apiFetch<PayrollLine[]>(
          `/payroll/runs/${runId}/lines`
        );
        setLines(data);
      } catch (err) {
        setLinesError(
          err instanceof ApiError ? err.message : "Gagal memuat daftar slip."
        );
      } finally {
        setLinesLoading(false);
      }
    }
    void loadLines();
  }, [runId]);

  const run = runs.find((r) => r.id === runId);
  const myEmploymentId = pinStatus?.employment_id ?? null;

  function pinErrorText(e: unknown): string {
    if (e instanceof ApiError) {
      return PIN_ERROR_TEXT[e.message] ?? e.message;
    }
    return "Terjadi kesalahan. Coba lagi.";
  }

  async function doDownload(target: DownloadTarget, pin: string | null) {
    setDlBusy(target.employmentId);
    try {
      await apiDownload(
        `/payroll/runs/${target.runId}/payslip/${target.employmentId}.pdf`,
        `slip-${target.period}-${target.nik}.pdf`,
        pin ? { "X-Payslip-Pin": pin } : {}
      );
    } finally {
      setDlBusy(null);
    }
  }

  function openPinFlow(target: DownloadTarget) {
    setPinTarget(target);
    setPinValue("");
    setPinConfirm("");
    setPinError(null);
    setPinMode(pinStatus?.pin_set ? "masuk" : "buat");
  }

  async function download(line: PayrollLine) {
    const target: DownloadTarget = {
      runId,
      employmentId: line.employment_id,
      period: run?.period ?? "gaji",
      nik: line.nik,
    };
    if (myEmploymentId && line.employment_id === myEmploymentId) {
      openPinFlow(target);
      return;
    }
    try {
      await doDownload(target, null);
    } catch (err) {
      setPageError(
        err instanceof ApiError ? err.message : "Gagal mengunduh slip."
      );
    }
  }

  async function downloadMine(slip: MySlip) {
    openPinFlow({
      runId: slip.run_id,
      employmentId: slip.employment_id,
      period: slip.period,
      nik: slip.nik,
    });
  }

  async function submitPin() {
    setPinError(null);
    if (!/^\d{6}$/.test(pinValue)) {
      setPinError("PIN harus tepat 6 angka.");
      return;
    }
    setPinBusy(true);
    try {
      if (pinMode === "buat") {
        if (pinValue !== pinConfirm) {
          setPinError("Konfirmasi PIN tidak sama.");
          return;
        }
        await apiFetch("/payslip-pin/set", {
          method: "POST",
          body: JSON.stringify({
            pin: pinValue,
            pin_confirmation: pinConfirm,
          }),
        });
        setNotice("PIN slip berhasil dibuat. Unduhan dimulai…");
        await loadSelf();
        if (pinTarget) await doDownload(pinTarget, pinValue);
        setPinMode(null);
      } else if (pinMode === "masuk") {
        if (!pinTarget) return;
        await doDownload(pinTarget, pinValue);
        setPinMode(null);
      } else if (pinMode === "ganti") {
        if (!/^\d{6}$/.test(pinNew)) {
          setPinError("PIN baru harus tepat 6 angka.");
          return;
        }
        if (pinNew !== pinConfirm) {
          setPinError("Konfirmasi PIN baru tidak sama.");
          return;
        }
        await apiFetch("/payslip-pin/change", {
          method: "POST",
          body: JSON.stringify({
            current_pin: pinValue,
            new_pin: pinNew,
            new_pin_confirmation: pinConfirm,
          }),
        });
        setNotice("PIN slip berhasil diganti.");
        await loadSelf();
        setPinMode(null);
      }
    } catch (e) {
      setPinError(pinErrorText(e));
    } finally {
      setPinBusy(false);
    }
  }

  function openChangePin() {
    setPinTarget(null);
    setPinValue("");
    setPinNew("");
    setPinConfirm("");
    setPinError(null);
    setPinMode("ganti");
  }

  if (loading) return <Spinner label="Memuat periode payroll…" />;
  if (error) {
    return <ErrorBox message={error} onRetry={() => window.location.reload()} />;
  }

  return (
    <div>
      <PageHeader
        title="Slip gaji"
        subtitle="Unduh slip gaji per periode payroll. Slip Anda sendiri dilindungi PIN 6 angka."
      />

      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {pageError && (
        <div className="mb-4">
          <ErrorBox message={pageError} />
        </div>
      )}

      {myEmploymentId && (
        <div className="mb-4">
          <Card title="Slip saya">
            {mySlips.length === 0 ? (
              <EmptyState message="Belum ada slip gaji untuk Anda dari periode yang sudah dikunci." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {mySlips.map((s) => (
                  <li
                    key={s.run_id}
                    className="flex flex-wrap items-center gap-3 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-800">
                        Slip {namaBulan(s.period)}
                      </p>
                      <p className="text-xs text-slate-500">
                        Take-home pay {rupiah(s.take_home_pay)}
                      </p>
                    </div>
                    <button
                      className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                      disabled={dlBusy === s.employment_id}
                      onClick={() => void downloadMine(s)}
                    >
                      {dlBusy === s.employment_id
                        ? "Mengunduh…"
                        : "🔒 Unduh PDF"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
              <span className="text-xs text-slate-500">
                {pinStatus?.pin_set
                  ? pinStatus.locked
                    ? "PIN sedang terkunci sementara (terlalu banyak percobaan salah). Minta HR mereset bila mendesak."
                    : "PIN slip aktif. Setiap unduhan slip Anda meminta PIN."
                  : "Anda belum mengatur PIN slip. PIN dibuat saat pertama kali mengunduh slip."}
              </span>
              {pinStatus?.pin_set && !pinStatus.locked && (
                <button className={btnSmall} onClick={openChangePin}>
                  Ganti PIN
                </button>
              )}
            </div>
          </Card>
        </div>
      )}

      {canViewAll && (
        <>
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
                {run?.totals &&
                  typeof run.totals.take_home_pay === "number" && (
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
                {!linesLoading && !linesError &&
                  (lines.length === 0 ? (
                    <EmptyState message="Tidak ada slip pada periode ini." />
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200 text-sm">
                        <thead className="bg-slate-50">
                          <tr>
                            <th className="px-4 py-3 text-left font-medium text-slate-600">
                              Nama
                            </th>
                            <th className="px-4 py-3 text-left font-medium text-slate-600">
                              NIK
                            </th>
                            <th className="px-4 py-3 text-right font-medium text-slate-600">
                              Bruto
                            </th>
                            <th className="px-4 py-3 text-right font-medium text-slate-600">
                              Potongan
                            </th>
                            <th className="px-4 py-3 text-right font-medium text-slate-600">
                              PPh 21
                            </th>
                            <th className="px-4 py-3 text-right font-medium text-slate-600">
                              Take-home
                            </th>
                            <th className="px-4 py-3 text-left font-medium text-slate-600">
                              Aksi
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {lines.map((l) => (
                            <tr key={l.id} className="hover:bg-slate-50">
                              <td className="px-4 py-3 font-medium text-slate-900">
                                {l.person_name}
                              </td>
                              <td className="px-4 py-3 font-mono text-xs text-slate-600">
                                {l.nik}
                              </td>
                              <td className="px-4 py-3 text-right text-slate-600">
                                {rupiah(l.gross)}
                              </td>
                              <td className="px-4 py-3 text-right text-slate-600">
                                {rupiah(l.total_deductions)}
                              </td>
                              <td className="px-4 py-3 text-right text-slate-600">
                                {rupiah(l.pph21)}
                              </td>
                              <td className="px-4 py-3 text-right font-semibold text-slate-900">
                                {rupiah(l.take_home_pay)}
                              </td>
                              <td className="px-4 py-3">
                                <button
                                  onClick={() => void download(l)}
                                  disabled={dlBusy === l.id}
                                  className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`}
                                >
                                  {dlBusy === l.id
                                    ? "Mengunduh…"
                                    : myEmploymentId &&
                                        l.employment_id === myEmploymentId
                                      ? "🔒 Unduh PDF"
                                      : "Unduh PDF"}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
              </Card>
            </div>
          )}
        </>
      )}

      {pinMode && (
        <Modal
          title={
            pinMode === "buat"
              ? "Buat PIN slip gaji"
              : pinMode === "ganti"
                ? "Ganti PIN slip gaji"
                : "Masukkan PIN slip"
          }
          onClose={() => setPinMode(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                onClick={() => setPinMode(null)}
              >
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={pinBusy}
                onClick={() => void submitPin()}
              >
                {pinBusy
                  ? "Memproses…"
                  : pinMode === "buat"
                    ? "Buat PIN & unduh"
                    : pinMode === "ganti"
                      ? "Simpan PIN baru"
                      : "Unduh slip"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              {pinMode === "buat"
                ? "Buat PIN 6 angka untuk melindungi slip gaji Anda. PIN dipakai setiap kali mengunduh slip sendiri."
                : pinMode === "ganti"
                  ? "Masukkan PIN lama, lalu PIN baru 6 angka."
                  : "Slip gaji Anda dilindungi PIN. Masukkan PIN 6 angka untuk mengunduh."}
            </p>
            <Field label={pinMode === "ganti" ? "PIN lama" : "PIN (6 angka)"}>
              <input
                className={inputCls}
                type="password"
                inputMode="numeric"
                autoComplete="off"
                maxLength={6}
                value={pinValue}
                onChange={(e) =>
                  setPinValue(e.target.value.replace(/\D/g, ""))
                }
                placeholder="••••••"
              />
            </Field>
            {pinMode === "ganti" && (
              <Field label="PIN baru (6 angka)">
                <input
                  className={inputCls}
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={6}
                  value={pinNew}
                  onChange={(e) =>
                    setPinNew(e.target.value.replace(/\D/g, ""))
                  }
                  placeholder="••••••"
                />
              </Field>
            )}
            {(pinMode === "buat" || pinMode === "ganti") && (
              <Field
                label={
                  pinMode === "buat"
                    ? "Konfirmasi PIN"
                    : "Konfirmasi PIN baru"
                }
              >
                <input
                  className={inputCls}
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={6}
                  value={pinConfirm}
                  onChange={(e) =>
                    setPinConfirm(e.target.value.replace(/\D/g, ""))
                  }
                  placeholder="••••••"
                />
              </Field>
            )}
            {pinError && <ErrorBox message={pinError} />}
            <p className="text-xs text-slate-400">
              5 kali PIN salah berturut-turut mengunci akses selama 15
              menit. Lupa PIN? Minta HR mereset PIN Anda.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
