"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type { Person } from "@/lib/types";
import { tanggal } from "@/lib/format";
import { PageHeader, Spinner, ErrorBox, EmptyState, inputCls, btnPrimary } from "@/components/ui";

export default function KaryawanPage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<Person[]>("/persons");
      setPersons(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data karyawan.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return persons;
    return persons.filter(
      (p) =>
        p.full_name.toLowerCase().includes(q) ||
        p.nik.includes(q) ||
        (p.email ?? "").toLowerCase().includes(q)
    );
  }, [persons, query]);

  if (loading) return <Spinner label="Memuat data karyawan…" />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Karyawan"
        subtitle={`${filtered.length} dari ${persons.length} karyawan`}
        action={
          <Link href="/karyawan/baru" className={btnPrimary}>
            + Tambah karyawan
          </Link>
        }
      />

      <div className="mb-4 max-w-md">
        <input
          className={inputCls}
          placeholder="Cari nama, NIK, atau email…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState message={query ? "Tidak ada karyawan yang cocok dengan pencarian." : "Belum ada data karyawan."} />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Nama</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">NIK</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Email</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Tgl. lahir</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">PTKP</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-900">{p.full_name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{p.nik}</td>
                  <td className="px-4 py-3 text-slate-600">{p.email ?? "-"}</td>
                  <td className="px-4 py-3 text-slate-600">{tanggal(p.birth_date)}</td>
                  <td className="px-4 py-3 text-slate-600">{p.ptkp}</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/karyawan/${p.id}`}
                      className="font-medium text-brand-600 hover:text-brand-700"
                    >
                      Detail
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
