"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, getToken } from "@/components/AuthContext";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

type TableInfo = { table: string; rows: number };
type BackupInfo = {
  tenant_id: string;
  storage_backend: string;
  tables: TableInfo[];
  total_rows: number;
};

export default function AdminBackupPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [info, setInfo] = useState<BackupInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (user && !user.is_superadmin) {
      router.replace("/dashboard");
      return;
    }
    if (!user) return;
    (async () => {
      try {
        const res = await fetch(`${BASE}/admin/backup/info`, {
          headers: { Authorization: `Bearer ${getToken()}` },
        });
        if (!res.ok) throw new Error(`Gagal memuat info backup (${res.status})`);
        setInfo(await res.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : "Gagal memuat info backup.");
      } finally {
        setLoading(false);
      }
    })();
  }, [user, router]);

  async function download() {
    setDownloading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`${BASE}/admin/backup/export`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error(`Gagal mengunduh backup (${res.status})`);
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") ?? "";
      const m = cd.match(/filename="([^"]+)"/);
      const name = m ? m[1] : "hrisx-backup.json";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setNotice(
        "Backup berhasil diunduh. Simpan berkas di tempat aman — berkas ini berisi seluruh data tenant."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal mengunduh backup.");
    } finally {
      setDownloading(false);
    }
  }

  if (!user || !user.is_superadmin) {
    return (
      <div className="p-8">
        <p className="text-slate-500">Memeriksa izin…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-bold text-slate-900">Backup Data</h1>
      <p className="mt-1 text-sm text-slate-500">
        Unduh salinan seluruh data tenant sebagai berkas JSON. Hanya superadmin.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {notice && (
        <div className="mt-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
          {notice}
        </div>
      )}

      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-semibold text-slate-900">Ekspor backup</p>
            <p className="mt-0.5 text-sm text-slate-500">
              {loading
                ? "Memuat ringkasan…"
                : info
                  ? `${info.total_rows} baris data dalam ${info.tables.length} tabel`
                  : "—"}
            </p>
            {info && (
              <p className="mt-1 text-xs text-slate-400">
                Penyimpanan berkas:{" "}
                <span className="font-medium text-slate-600">
                  {info.storage_backend === "cloudinary"
                    ? "Cloudinary (durable)"
                    : "Lokal server (ephemeral di serverless)"}
                </span>
              </p>
            )}
          </div>
          <button
            onClick={download}
            disabled={downloading || loading}
            className="rounded-lg bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
          >
            {downloading ? "Mengunduh…" : "💾 Unduh Backup"}
          </button>
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="font-semibold text-slate-900">Panduan pemulihan</p>
        <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-slate-600">
          <li>
            Database Neon memiliki point-in-time recovery bawaan — untuk
            insiden &lt; 1×24 jam, pulihkan lewat Neon Console → Branches →
            Restore.
          </li>
          <li>
            Untuk arsip mandiri: unduh backup JSON di atas secara berkala dan
            simpan di luar platform.
          </li>
          <li>
            Uji restore: buat branch Neon baru (kosong), lalu jalankan{" "}
            <code className="rounded bg-slate-100 px-1 text-xs">
              backend/scripts/restore_backup.py
            </code>{" "}
            dengan <code className="rounded bg-slate-100 px-1 text-xs">DATABASE_URL</code>{" "}
            mengarah ke branch tersebut.
          </li>
          <li>
            Backup otomatis harian (pg_dump) berjalan via GitHub Actions setelah
            secret <code className="rounded bg-slate-100 px-1 text-xs">DATABASE_URL_BACKUP</code>{" "}
            diisi di pengaturan repo.
          </li>
        </ol>
      </div>
    </div>
  );
}
