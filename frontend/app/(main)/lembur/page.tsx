"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  OvertimeRequest,
  OvertimeRate,
  Me,
  Person,
  Employment,
} from "@/lib/types";
import { tanggal, rupiah } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  StatusChip,
  Field,
  inputCls,
  btnPrimary,
} from "@/components/ui";

function jam(iso: string | null): string {
  if (!iso) return "—";
  // ISO naive "2026-10-02T18:00:00" → "18:00"
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : iso;
}

export default function LemburPage() {
  const [requests, setRequests] = useState<OvertimeRequest[]>([]);
  const [rate, setRate] = useState<OvertimeRate | null>(null);
  const [employmentId, setEmploymentId] = useState("");
  const [personMap, setPersonMap] = useState<Map<string, string>>(new Map());
  const [empPerson, setEmpPerson] = useState<Map<string, string>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [date, setDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [reqs, rt, me, persons, emps] = await Promise.all([
        apiFetch<OvertimeRequest[]>("/overtime/requests"),
        apiFetch<OvertimeRate>("/overtime/rate"),
        apiFetch<Me>("/me"),
        apiFetch<Person[]>("/persons"),
        apiFetch<Employment[]>("/employments"),
      ]);
      setRequests(reqs);
      setRate(rt);
      setPersonMap(new Map(persons.map((p) => [p.id, p.full_name])));
      setEmpPerson(new Map(emps.map((e) => [e.id, e.person_id])));
      const mePersonId =
        me.person_id ??
        persons.find(
          (p) => (p.email ?? "").toLowerCase() === me.email.toLowerCase()
        )?.id;
      const mine = emps.filter(
        (e) => mePersonId != null && e.person_id === mePersonId && e.status === "active"
      );
      setEmploymentId(mine[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data lembur.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const empName = (employmentId: string) =>
    personMap.get(empPerson.get(employmentId) ?? "") ?? "—";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!employmentId) {
      setFormError("Data employment Anda tidak ditemukan. Hubungi HR.");
      return;
    }
    if (!date || !startTime || !endTime) {
      setFormError("Tanggal, jam mulai, dan jam selesai wajib diisi.");
      return;
    }
    setBusy(true);
    try {
      const created = await apiFetch<OvertimeRequest>("/overtime/requests", {
        method: "POST",
        body: JSON.stringify({
          employment_id: employmentId,
          date,
          start_time: startTime,
          end_time: endTime,
          reason: reason.trim() || null,
        }),
      });
      // Langsung submit agar masuk antrean persetujuan atasan (pra-persetujuan).
      const submitted = await apiFetch<OvertimeRequest>(
        `/overtime/requests/${created.id}/submit`,
        { method: "POST" }
      );
      setRequests((r) => [submitted, ...r]);
      setDate("");
      setStartTime("");
      setEndTime("");
      setReason("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal mengajukan lembur.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Memuat data lembur…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Lembur"
        subtitle="Ajukan lembur (pra-persetujuan) dan pantau statusnya"
        action={
          <Link
            href="/lembur/persetujuan"
            className="text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            Ke halaman persetujuan →
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Pengajuan lembur baru" className="lg:col-span-2">
          {formError && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {formError}
            </div>
          )}
          <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Tanggal lembur" required>
              <input
                className={inputCls}
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
              />
            </Field>
            <div />
            <Field label="Jam mulai" required>
              <input
                className={inputCls}
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
              />
            </Field>
            <Field label="Jam selesai" required>
              <input
                className={inputCls}
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                required
              />
            </Field>
            <div className="md:col-span-2">
              <Field label="Alasan / pekerjaan yang dilakukan">
                <textarea
                  className={inputCls}
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Contoh: menyelesaikan laporan bulanan…"
                />
              </Field>
            </div>
            <div className="md:col-span-2">
              <button type="submit" disabled={busy} className={btnPrimary}>
                {busy ? "Mengirim…" : "Ajukan lembur"}
              </button>
              <p className="mt-2 text-xs text-slate-500">
                Pengajuan otomatis disubmit dan diteruskan ke atasan untuk
                persetujuan level 1. Lembur yang dibayar adalah yang sudah
                disetujui (pra-persetujuan).
              </p>
            </div>
          </form>
        </Card>

        <Card title="Ketentuan upah lembur">
          {rate ? (
            <ul className="space-y-2 text-sm text-slate-600">
              <li>
                Upah per jam = gaji pokok ÷ {rate.divisor}
              </li>
              <li>Jam pertama: {String(rate.first_hour_mult).replace(".", ",")}× upah per jam</li>
              <li>
                Jam berikutnya: {String(rate.next_hour_mult).replace(".", ",")}× upah per jam
              </li>
              <li>Maksimal 4 jam per hari (PP 35/2021)</li>
              <li>Lembur lewat tengah malam didukung</li>
            </ul>
          ) : (
            <EmptyState message="Ketentuan upah tidak tersedia." />
          )}
        </Card>
      </div>

      <div className="mt-4">
        <Card title="Riwayat pengajuan lembur">
          {requests.length === 0 ? (
            <EmptyState message="Belum ada pengajuan lembur." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Karyawan</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Tanggal</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Jam</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Durasi</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Status</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Upah</th>
                    <th className="px-4 py-3 text-left font-medium text-slate-600">Alasan</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {requests.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-medium text-slate-900">
                        {empName(r.employment_id)}
                      </td>
                      <td className="px-4 py-3 text-slate-600">{tanggal(r.date)}</td>
                      <td className="px-4 py-3 text-slate-600">
                        {jam(r.start_time)}–{jam(r.end_time)}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {String(r.hours).replace(".", ",")} jam
                      </td>
                      <td className="px-4 py-3">
                        <StatusChip status={r.status} />
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {r.status === "approved" ? rupiah(r.pay_amount) : "—"}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {r.status === "rejected" && r.rejection_reason
                          ? `Ditolak: ${r.rejection_reason}`
                          : (r.reason ?? "-")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
