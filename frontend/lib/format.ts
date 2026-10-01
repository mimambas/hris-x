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
