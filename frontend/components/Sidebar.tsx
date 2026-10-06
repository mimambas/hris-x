"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthContext";

// Navigasi dikelompokkan mengikuti alur kerja HR: ringkasan &
// persetujuan dulu, lalu data & transaksi, terakhir pengembangan
// karyawan. Penanda aktif berupa pil biru konsol di atas latar
// navy gelap (bahasa desain baru, 2026-10-06).
export const NAV_GROUPS: { title: string | null; items: { href: string; label: string; icon: string }[] }[] = [
  {
    title: null,
    items: [
      { href: "/dashboard", label: "Dasbor", icon: "📊" },
      { href: "/kotak-masuk", label: "Kotak Masuk", icon: "📥" },
      { href: "/tim", label: "Dasbor Tim", icon: "🧑‍🤝‍🧑" },
      { href: "/report-builder", label: "Report Builder", icon: "📈" },
    ],
  },
  {
    title: "Data & Organisasi",
    items: [
      { href: "/karyawan", label: "Karyawan", icon: "👥" },
      { href: "/org", label: "Organisasi", icon: "🏢" },
      { href: "/onboarding", label: "Onboarding", icon: "👋" },
      { href: "/profil", label: "Profil & Data Saya", icon: "👤" },
    ],
  },
  {
    title: "Waktu & Kehadiran",
    items: [
      { href: "/absensi", label: "Absensi", icon: "⏰" },
      { href: "/roster", label: "Roster & Tukar Shift", icon: "🗓️" },
      { href: "/cuti", label: "Cuti", icon: "🌴" },
      { href: "/cuti/persetujuan", label: "Persetujuan Cuti", icon: "✅" },
      { href: "/lembur", label: "Lembur", icon: "🌙" },
      { href: "/lembur/persetujuan", label: "Persetujuan Lembur", icon: "🆗" },
    ],
  },
  {
    title: "Penggajian & Manfaat",
    items: [
      { href: "/slip", label: "Slip Gaji", icon: "🧾" },
      { href: "/klaim", label: "Klaim", icon: "💸" },
      { href: "/klaim/persetujuan", label: "Persetujuan Klaim", icon: "✅" },
      { href: "/pinjaman", label: "Pinjaman", icon: "🏦" },
      { href: "/pinjaman/persetujuan", label: "Persetujuan Pinjaman", icon: "✔️" },
      { href: "/kompensasi", label: "Kompensasi", icon: "💰" },
    ],
  },
  {
    title: "Talent & Pengembangan",
    items: [
      { href: "/rekrutmen/lowongan", label: "Rekrutmen", icon: "💼" },
      { href: "/rekrutmen/kandidat", label: "Kandidat", icon: "🧑‍💼" },
      { href: "/penilaian", label: "Penilaian", icon: "🎯" },
      { href: "/pelatihan", label: "Pelatihan", icon: "🎓" },
      { href: "/suksesi", label: "Suksesi & Karier", icon: "🌟" },
      { href: "/keterlibatan", label: "Keterlibatan", icon: "💬" },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === href || pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ href, label, icon, pathname }: { href: string; label: string; icon: string; pathname: string }) {
  const active = isActive(pathname, href);
  return (
    <Link
      href={href}
      className={`group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? "bg-brand-600 text-white shadow-sm"
          : "text-slate-300 hover:bg-white/5 hover:text-white"
      }`}
    >
      {active && (
        <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-full bg-white/90" aria-hidden />
      )}
      <span aria-hidden className="text-[15px] leading-none">{icon}</span>
      {label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col bg-ink-950 text-slate-200">
      <div className="flex items-center gap-3 px-5 pb-5 pt-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand-600 text-lg font-bold text-white shadow-sm">
          H
        </div>
        <div>
          <p className="text-[15px] font-bold leading-tight tracking-tight text-white">HRIS-X</p>
          <p className="text-[11px] leading-tight text-slate-400">Sistem Informasi SDM</p>
        </div>
      </div>

      <nav className="nav-scroll flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className="space-y-1">
            {group.title && (
              <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                {group.title}
              </p>
            )}
            {group.items.map((item) => (
              <NavLink key={item.href} {...item} pathname={pathname} />
            ))}
          </div>
        ))}
        {user?.is_superadmin && (
          <div className="space-y-1">
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Admin
            </p>
            <NavLink href="/admin/backup" label="Backup" icon="💾" pathname={pathname} />
          </div>
        )}
      </nav>

    </aside>
  );
}
