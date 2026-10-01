"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthContext";

const NAV = [
  { href: "/dashboard", label: "Dasbor", icon: "📊" },
  { href: "/karyawan", label: "Karyawan", icon: "👥" },
  { href: "/cuti", label: "Cuti", icon: "🌴" },
  { href: "/cuti/persetujuan", label: "Persetujuan Cuti", icon: "✅" },
  { href: "/absensi", label: "Absensi", icon: "⏰" },
  { href: "/rekrutmen/lowongan", label: "Rekrutmen", icon: "💼" },
  { href: "/rekrutmen/kandidat", label: "Kandidat", icon: "🧑‍💼" },
  { href: "/slip", label: "Slip Gaji", icon: "🧾" },
  { href: "/org", label: "Organisasi", icon: "🏢" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === href || pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col bg-slate-900 text-slate-200">
      <div className="px-5 pb-4 pt-6">
        <p className="text-lg font-bold tracking-tight text-white">HRIS-X</p>
        <p className="mt-0.5 text-xs text-slate-400">Sistem Informasi SDM</p>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-brand-600 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-slate-800 p-4">
        {user && (
          <div className="mb-3 px-1">
            <p className="truncate text-sm font-medium text-white">{user.full_name}</p>
            <p className="truncate text-xs text-slate-400">{user.email}</p>
            {user.roles.length > 0 && (
              <p className="mt-1 truncate text-xs text-slate-500">
                {user.roles.join(", ")}
              </p>
            )}
          </div>
        )}
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white"
        >
          <span aria-hidden>🚪</span>
          Keluar
        </button>
      </div>
    </aside>
  );
}
