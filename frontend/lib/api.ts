// Wrapper fetch ke backend HRIS-X.
// - Base URL dari NEXT_PUBLIC_API_URL (jangan hardcode di komponen).
// - Token JWT otomatis dipasang dari localStorage.
// - 401 → token dihapus + redirect ke /login.
// - 403/404 → pesan ramah Bahasa Indonesia.

import { getToken, clearAuth } from "@/components/AuthContext";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function friendlyMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim().length > 0) return detail;
  if (status === 400) return "Permintaan tidak valid. Periksa kembali isian Anda.";
  if (status === 401) return "Sesi Anda telah berakhir. Silakan masuk kembali.";
  if (status === 403)
    return "Anda tidak memiliki izin untuk mengakses data ini.";
  if (status === 404) return "Data tidak ditemukan.";
  if (status === 409) return "Data sudah ada (duplikat).";
  if (status === 422) return "Validasi gagal. Periksa kembali isian Anda.";
  if (status === 429)
    return "Terlalu banyak percobaan. Tunggu sebentar lalu coba lagi.";
  if (status >= 500) return "Terjadi kesalahan pada server. Coba lagi nanti.";
  return "Terjadi kesalahan. Coba lagi.";
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Tidak dapat terhubung ke server. Periksa koneksi Anda.");
  }

  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, friendlyMessage(401, null));
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? null;
    } catch {
      /* abaikan */
    }
    throw new ApiError(res.status, friendlyMessage(res.status, detail));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// Unggah berkas multipart beserta field form tambahan (mis. struk klaim:
// doc_type, employment_id, notes). Tidak memakai Content-Type:
// application/json agar browser mengisi boundary sendiri.
export async function apiUploadForm<T>(
  path: string,
  fields: Record<string, string>,
  file: File
): Promise<T> {
  const token = getToken();
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  form.append("file", file);
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form, headers });
  } catch {
    throw new ApiError(0, "Tidak dapat terhubung ke server. Periksa koneksi Anda.");
  }

  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, friendlyMessage(401, null));
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? null;
    } catch {
      /* abaikan */
    }
    throw new ApiError(res.status, friendlyMessage(res.status, detail));
  }
  return (await res.json()) as T;
}

// Unduh file biner (PDF slip gaji) dengan header Authorization.
export async function apiDownload(
  path: string,
  filename: string,
  extraHeaders: Record<string, string> = {}
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = { ...extraHeaders };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { headers });
  } catch {
    throw new ApiError(0, "Tidak dapat terhubung ke server. Periksa koneksi Anda.");
  }
  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, friendlyMessage(401, null));
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? null;
    } catch {
      /* abaikan */
    }
    throw new ApiError(res.status, friendlyMessage(res.status, detail));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Base URL API untuk halaman yang butuh fetch mentah (mis. halaman publik
// tanpa redirect login otomatis).
export function getApiBase(): string {
  return BASE;
}

// Unggah berkas multipart (mis. CV kandidat). Tidak memakai
// Content-Type: application/json agar browser mengisi boundary sendiri.
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form, headers });
  } catch {
    throw new ApiError(0, "Tidak dapat terhubung ke server. Periksa koneksi Anda.");
  }

  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, friendlyMessage(401, null));
  }

  if (!res.ok) {
    let detail: unknown = null;
    try {
      const body = await res.json();
      detail = body?.detail ?? null;
    } catch {
      /* abaikan */
    }
    throw new ApiError(res.status, friendlyMessage(res.status, detail));
  }
  return (await res.json()) as T;
}
