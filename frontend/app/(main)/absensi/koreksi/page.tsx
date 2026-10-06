"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  AttendanceRecord,
  Employment,
  Person,
} from "@/lib/types";
import { tanggal, tanggalWaktuLokal, parseWaktuLokal, todayISO } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  Field,
  inputCls,
  btnPrimary,
} from "@/components/ui";


function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  // Backend menyimpan waktu lokal-naif (ADR-0008): tampilkan sebagai
  // wall-clock tanpa konversi zona waktu.
  const d = parseWaktuLokal(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function fromLocalInput(v: string): string | null {
  if (!v) return null;
  // Input datetime-local "YYYY-MM-DDTHH:mm" sudah berupa waktu lokal-naif;
  // kirim apa adanya (tanpa toISOString()) sesuai konvensi backend.
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v)) return null;
  return `${v}:00`;
}

interface Option {
  employmentId: string;
  name: string;
}

export default function KoreksiAbsensiPage() {
  const [options, setOptions] = useState<Option[]>([]);
  const [employmentId, setEmploymentId] = useState("");
  const [date, setDate] = useState(todayISO());
  const [record, setRecord] = useState<AttendanceRecord | null>(null);
  const [searched, setSearched] = useState(false);
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [persons, emps] = await Promise.all([
          apiFetch<Person[]>("/persons"),
          apiFetch<Employment[]>("/employments"),
        ]);
        const personById = new Map(persons.map((p) => [p.id, p]));
        // Hanya tawarkan employment yang person-nya terlihat oleh user
        // (daftar /persons sudah menghormati target population). Ini
        // mencegah opsi berlabel rusak sekaligus opsi yang pasti ditolak
        // 403 oleh RBP backend.
        const visiblePersonIds = new Set(persons.map((p) => p.id));
        const opts = emps
          .filter((e) => e.status === "active" && visiblePersonIds.has(e.person_id))
          .map((e) => ({
            employmentId: e.id,
            name: personById.get(e.person_id)?.full_name ?? "Tanpa nama",
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

  const selectedName = useMemo(
    () => options.find((o) => o.employmentId === employmentId)?.name ?? "",
    [options, employmentId]
  );

  async function cari() {
    if (!employmentId || !date) return;
    setBusy(true);
    setFormError(null);
    setSuccess(null);
    try {
      const recs = await apiFetch<AttendanceRecord[]>(
        `/attendance/records?employment_id=${employmentId}&date_from=${date}&date_to=${date}`
      );
      const rec = recs[0] ?? null;
      setRecord(rec);
      setCheckIn(toLocalInput(rec?.check_in ?? null));
      setCheckOut(toLocalInput(rec?.check_out ?? null));
      setReason("");
      setSearched(true);
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Gagal mencari record absensi."
      );
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!record) return;
    setFormError(null);
    setSuccess(null);
    if (!reason.trim()) {
      setFormError("Alasan koreksi wajib diisi.");
      return;
    }
    const ci = fromLocalInput(checkIn);
    const co = fromLocalInput(checkOut);
    if (checkIn && !ci) {
      setFormError("Format jam masuk tidak valid.");
      return;
    }
    if (checkOut && !co) {
      setFormError("Format jam keluar tidak valid.");
      return;
    }
    setBusy(true);
    try {
      const updated = await apiFetch<AttendanceRecord>(
        `/attendance/${record.id}/correct`,
        {
          method: "POST",
          body: JSON.stringify({
            check_in: ci,
            check_out: co,
            reason: reason.trim(),
          }),
        }
      );
      setRecord(updated);
      setSuccess(
        `Koreksi tersimpan (versi ${updated.version}). Status: ${updated.status}.`
      );
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Gagal menyimpan koreksi."
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Memuat data karyawan…" />;
  if (error) return <ErrorBox message={error} onRetry={() => location.reload()} />;

  return (
    <div>
      <PageHeader
        title="Koreksi Kehadiran"
        subtitle="Perbaiki jam masuk/keluar yang salah catat dengan alasan yang jelas"
      />

      {success && (
        <div className="mb-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-emerald-200">
          {success}
        </div>
      )}
      {formError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
          {formError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Cari record">
          <div className="space-y-3">
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
            <Field label="Tanggal">
              <input
                type="date"
                value={date}
                max={todayISO()}
                onChange={(e) => e.target.value && setDate(e.target.value)}
                className={inputCls}
              />
            </Field>
            <button className={btnPrimary} disabled={busy} onClick={cari}>
              {busy ? "Mencari…" : "Tampilkan record"}
            </button>
          </div>
        </Card>

        <Card title="Koreksi">
          {!searched ? (
            <EmptyState message="Pilih karyawan dan tanggal, lalu tampilkan record." />
          ) : !record ? (
            <EmptyState
              message={`${selectedName} tidak memiliki record absensi pada ${tanggal(date)}.`}
            />
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg bg-slate-50 p-3 text-sm">
                <p className="font-medium text-slate-900">{selectedName}</p>
                <p className="text-slate-500">
                  {tanggal(record.date)} · versi {record.version} · status{" "}
                  {record.status}
                </p>
                <p className="mt-1 text-slate-600">
                  Tercatat: masuk{" "}
                  {record.check_in ? tanggalWaktuLokal(record.check_in) : "-"} ·
                  keluar {record.check_out ? tanggalWaktuLokal(record.check_out) : "-"}
                </p>
                {record.correction_reason && (
                  <p className="mt-1 text-xs text-slate-400">
                    Koreksi sebelumnya: {record.correction_reason}
                  </p>
                )}
              </div>
              <Field label="Jam masuk (baru)">
                <input
                  type="datetime-local"
                  value={checkIn}
                  onChange={(e) => setCheckIn(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Jam keluar (baru)">
                <input
                  type="datetime-local"
                  value={checkOut}
                  onChange={(e) => setCheckOut(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="Alasan koreksi (wajib)">
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  placeholder="Contoh: lupa check-out, mesin absensi error…"
                  className={inputCls}
                />
              </Field>
              <button className={btnPrimary} disabled={busy} onClick={submit}>
                {busy ? "Menyimpan…" : "Simpan koreksi"}
              </button>
              <p className="text-xs text-slate-400">
                Koreksi membuat versi baru dari record; riwayat versi lama tetap
                tersimpan dan tercatat di audit.
              </p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
