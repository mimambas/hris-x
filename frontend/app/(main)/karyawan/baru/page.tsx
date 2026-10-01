"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, ApiError } from "@/lib/api";
import type { Person } from "@/lib/types";
import { PageHeader, Card, Field, inputCls, btnPrimary, btnSecondary } from "@/components/ui";

const PTKP_OPTIONS = [
  "TK/0", "TK/1", "TK/2", "TK/3",
  "K/0", "K/1", "K/2", "K/3",
  "K/I/0", "K/I/1", "K/I/2", "K/I/3",
];

export default function KaryawanBaruPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    nik: "",
    full_name: "",
    birth_place: "",
    birth_date: "",
    gender: "",
    email: "",
    phone: "",
    npwp: "",
    ptkp: "TK/0",
    bpjs_kes_no: "",
    bpjs_tk_no: "",
    bank_name: "",
    bank_account_no: "",
    reason: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function opt(v: string): string | null {
    const t = v.trim();
    return t.length > 0 ? t : null;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\d{16}$/.test(form.nik.trim())) {
      setError("NIK harus terdiri dari 16 digit angka.");
      return;
    }
    setBusy(true);
    try {
      const created = await apiFetch<Person>("/persons", {
        method: "POST",
        body: JSON.stringify({
          nik: form.nik.trim(),
          full_name: form.full_name.trim(),
          birth_place: opt(form.birth_place),
          birth_date: opt(form.birth_date),
          gender: opt(form.gender),
          email: opt(form.email),
          phone: opt(form.phone),
          npwp: opt(form.npwp),
          ptkp: form.ptkp,
          bpjs_kes_no: opt(form.bpjs_kes_no),
          bpjs_tk_no: opt(form.bpjs_tk_no),
          bank_name: opt(form.bank_name),
          bank_account_no: opt(form.bank_account_no),
          reason: form.reason.trim(),
        }),
      });
      router.replace(`/karyawan/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal menyimpan data.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Tambah karyawan"
        subtitle="Data pribadi karyawan baru"
      />
      <Card>
        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}
        <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="NIK" required hint="16 digit angka">
            <input
              className={`${inputCls} font-mono`}
              value={form.nik}
              onChange={(e) => set("nik", e.target.value)}
              maxLength={16}
              inputMode="numeric"
              required
            />
          </Field>
          <Field label="Nama lengkap" required>
            <input
              className={inputCls}
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              required
            />
          </Field>
          <Field label="Tempat lahir">
            <input className={inputCls} value={form.birth_place} onChange={(e) => set("birth_place", e.target.value)} />
          </Field>
          <Field label="Tanggal lahir">
            <input className={inputCls} type="date" value={form.birth_date} onChange={(e) => set("birth_date", e.target.value)} />
          </Field>
          <Field label="Jenis kelamin">
            <select className={inputCls} value={form.gender} onChange={(e) => set("gender", e.target.value)}>
              <option value="">— Pilih —</option>
              <option value="L">Laki-laki</option>
              <option value="P">Perempuan</option>
            </select>
          </Field>
          <Field label="Email">
            <input className={inputCls} type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
          </Field>
          <Field label="Telepon">
            <input className={inputCls} value={form.phone} onChange={(e) => set("phone", e.target.value)} />
          </Field>
          <Field label="NPWP">
            <input className={inputCls} value={form.npwp} onChange={(e) => set("npwp", e.target.value)} />
          </Field>
          <Field label="Status PTKP" required>
            <select className={inputCls} value={form.ptkp} onChange={(e) => set("ptkp", e.target.value)}>
              {PTKP_OPTIONS.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </Field>
          <Field label="No. BPJS Kesehatan">
            <input className={inputCls} value={form.bpjs_kes_no} onChange={(e) => set("bpjs_kes_no", e.target.value)} />
          </Field>
          <Field label="No. BPJS Ketenagakerjaan">
            <input className={inputCls} value={form.bpjs_tk_no} onChange={(e) => set("bpjs_tk_no", e.target.value)} />
          </Field>
          <Field label="Nama bank">
            <input className={inputCls} value={form.bank_name} onChange={(e) => set("bank_name", e.target.value)} />
          </Field>
          <Field label="Nomor rekening">
            <input className={inputCls} value={form.bank_account_no} onChange={(e) => set("bank_account_no", e.target.value)} />
          </Field>
          <div className="md:col-span-2">
            <Field label="Alasan pencatatan" required hint="Wajib diisi — tercatat di jejak audit.">
              <input
                className={inputCls}
                value={form.reason}
                onChange={(e) => set("reason", e.target.value)}
                placeholder="mis. Rekrutmen karyawan baru"
                required
              />
            </Field>
          </div>
          <div className="flex gap-3 md:col-span-2">
            <button type="submit" disabled={busy} className={btnPrimary}>
              {busy ? "Menyimpan…" : "Simpan"}
            </button>
            <button type="button" onClick={() => router.back()} className={btnSecondary}>
              Batal
            </button>
          </div>
        </form>
      </Card>
    </div>
  );
}
