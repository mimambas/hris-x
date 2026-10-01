// Format tanggal & angka Bahasa Indonesia.

const rupiahFmt = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const angkaFmt = new Intl.NumberFormat("id-ID");

export function rupiah(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "-";
  return rupiahFmt.format(n);
}

export function angka(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "-";
  return angkaFmt.format(n);
}

export function persen(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "-";
  return `${n.toFixed(digits).replace(".", ",")}%`;
}

export function tanggal(iso: string | null | undefined): string {
  if (!iso) return "-";
  // Sentinel effective-dating "masih berlaku" → tampilkan "Sekarang",
  // bukan "31 Desember 9999" yang mentah.
  if (iso.startsWith("9999")) return "Sekarang";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("id-ID", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function tanggalWaktu(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("id-ID", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// --- Waktu lokal-naif (konvensi backend, ADR-0008) ---
//
// Backend menyimpan datetime absensi sebagai "waktu lokal-naif" (zona waktu
// lokasi kerja); kolom timestamptz Postgres mengembalikannya dengan offset
// UTC (mis. "2026-09-01T08:05:00Z" padahal maksudnya 08:05 WIB). Fungsi di
// bawah mem-parse sebagai wall-clock TANPA konversi zona waktu, agar jam
// yang tampil sama dengan yang dicatat. JANGAN dipakai untuk kolom yang
// memang menyimpan momen absolut (mis. created_at) — untuk itu pakai
// tanggalWaktu() biasa.
export function parseWaktuLokal(iso: string): Date {
  const tanpaOffset = iso.replace(/(Z|[+-]\d{2}:?\d{2})$/, "");
  return new Date(
    tanpaOffset.length <= 10 ? `${tanpaOffset}T00:00:00` : tanpaOffset
  );
}

export function jamLokal(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = parseWaktuLokal(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

export function tanggalWaktuLokal(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = parseWaktuLokal(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("id-ID", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ISO "waktu lokal-naif" untuk dikirim ke backend (tanpa offset zona waktu).
export function nowNaiveLocalISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

// "2026-09" → "September 2026"
export function namaBulan(period: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(period);
  if (!m) return period;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, 1);
  return d.toLocaleDateString("id-ID", { month: "long", year: "numeric" });
}

// "2026-09" → "Sep 26" (label grafik ringkas)
export function labelBulanSingkat(period: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(period);
  if (!m) return period;
  const nama = [
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
  ];
  return `${nama[Number(m[2]) - 1]} ${m[1].slice(2)}`;
}
