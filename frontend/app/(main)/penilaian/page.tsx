"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import { EmptyState, Modal } from "@/components/ui";

interface Cycle {
  id: string;
  name: string;
  year: number;
  status: string;
  start_date: string;
  end_date: string;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  goal_setting: "Penetapan Sasaran",
  mid_year: "Tinjauan Tengah Tahun",
  year_end: "Penilaian Akhir Tahun",
  calibration: "Kalibrasi",
  closed: "Ditutup",
};

const STATUS_ORDER = [
  "draft",
  "goal_setting",
  "mid_year",
  "year_end",
  "calibration",
  "closed",
];

function statusColor(s: string): string {
  switch (s) {
    case "draft":
      return "bg-slate-100 text-slate-700";
    case "goal_setting":
      return "bg-blue-100 text-blue-800";
    case "mid_year":
      return "bg-amber-100 text-amber-800";
    case "year_end":
      return "bg-violet-100 text-violet-800";
    case "calibration":
      return "bg-orange-100 text-orange-800";
    case "closed":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function nextStatus(s: string): string | null {
  const i = STATUS_ORDER.indexOf(s);
  return i >= 0 && i < STATUS_ORDER.length - 1 ? STATUS_ORDER[i + 1] : null;
}

export default function PenilaianPage() {
  const [cycles, setCycles] = useState<Cycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState<Cycle | null>(null);

  const [name, setName] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<Cycle[]>("/performance/cycles");
      setCycles(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat siklus.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createCycle(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !startDate || !endDate) {
      setFormError("Nama, tanggal mulai, dan tanggal selesai wajib diisi.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await apiFetch("/performance/cycles", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          year,
          start_date: startDate,
          end_date: endDate,
        }),
      });
      setShowForm(false);
      setName("");
      setStartDate("");
      setEndDate("");
      await load();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Gagal membuat siklus."
      );
    } finally {
      setBusy(false);
    }
  }

  async function doTransition(cycle: Cycle) {
    const to = nextStatus(cycle.status);
    if (!to) return;
    setBusy(true);
    try {
      await apiFetch(`/performance/cycles/${cycle.id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: to }),
      });
      setTransitioning(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal mengubah tahap.");
      setTransitioning(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Penilaian Kinerja</h1>
          <p className="mt-1 text-sm text-slate-500">
            Siklus penilaian tahunan: penetapan sasaran → penilaian → kalibrasi
            9-box.
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + Siklus baru
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Memuat…</p>
      ) : cycles.length === 0 ? (
        <EmptyState message="Belum ada siklus penilaian. Buat siklus baru untuk memulai." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Nama siklus</th>
                <th className="px-4 py-3">Tahun</th>
                <th className="px-4 py-3">Periode</th>
                <th className="px-4 py-3">Tahap</th>
                <th className="px-4 py-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((c) => {
                const next = nextStatus(c.status);
                return (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="px-4 py-3 font-medium text-slate-900">
                      <Link
                        href={`/penilaian/${c.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {c.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{c.year}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {c.start_date} s.d. {c.end_date}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2.5 py-1 text-xs font-medium ${statusColor(c.status)}`}
                      >
                        {STATUS_LABEL[c.status] ?? c.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {next && (
                        <button
                          onClick={() => setTransitioning(c)}
                          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                        >
                          Lanjut ke {STATUS_LABEL[next]}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <Modal
          title="Buat siklus penilaian"
          onClose={() => !busy && setShowForm(false)}
          actions={
            <>
              <button
                onClick={() => setShowForm(false)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={createCycle}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Simpan"}
              </button>
            </>
          }
        >
          <form onSubmit={createCycle} className="space-y-3">
            {formError && (
              <p className="rounded bg-red-50 p-2 text-xs text-red-700">
                {formError}
              </p>
            )}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Nama siklus
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="cth. Penilaian Tahunan 2026"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Tahun
              </label>
              <input
                type="number"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-700">
                  Tanggal mulai
                </label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-700">
                  Tanggal selesai
                </label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
            </div>
          </form>
        </Modal>
      )}

      {transitioning && nextStatus(transitioning.status) && (
        <Modal
          title="Lanjut ke tahap berikutnya"
          onClose={() => !busy && setTransitioning(null)}
          actions={
            <>
              <button
                onClick={() => setTransitioning(null)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={() => doTransition(transitioning)}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Memproses…" : "Ya, lanjutkan"}
              </button>
            </>
          }
        >
          <p>
            Pindahkan siklus <strong>{transitioning.name}</strong> dari tahap{" "}
            <strong>{STATUS_LABEL[transitioning.status]}</strong> ke{" "}
            <strong>
              {STATUS_LABEL[nextStatus(transitioning.status) as string]}
            </strong>
            ?
          </p>
          {transitioning.status === "calibration" && (
            <p className="mt-2 text-amber-700">
              Perhatian: tahap berikutnya adalah “Ditutup” — siklus yang
              ditutup tidak bisa diubah lagi.
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
