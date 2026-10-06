"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthContext";
import { NotificationBell } from "@/components/notifikasi";
import { NAV_GROUPS } from "@/components/Sidebar";

// Bilah atas konsol (2026-10-06): konteks halaman aktif di kiri,
// identitas pengguna + notifikasi + keluar di kanan. Sidebar
// menjadi murni navigasi; identitas tidak lagi diduplikasi.
function activeLabel(pathname: string): string {
  let best: { href: string; label: string } | null = null;
  for (const g of NAV_GROUPS) {
    for (const item of g.items) {
      const hit =
        pathname === item.href || pathname.startsWith(`${item.href}/`);
      if (hit && (!best || item.href.length > best.href.length)) best = item;
    }
  }
  if (pathname.startsWith("/admin/backup"))
    return "Backup";
  return best?.label ?? "Beranda";
}

export function Topbar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-slate-200/80 bg-white/85 px-6 py-3 backdrop-blur lg:px-10">
      <div className="flex items-center gap-3">
        <p className="text-sm font-semibold tracking-tight text-slate-900">
          {activeLabel(pathname)}
        </p>
        <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-brand-700 ring-1 ring-inset ring-brand-100">
          Staging
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3">
        <NotificationBell />
        {user && (
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-ink-800 text-sm font-semibold text-white">
              {(user.full_name || "?").charAt(0).toUpperCase()}
            </div>
            <div className="hidden min-w-0 sm:block">
              <p className="max-w-44 truncate text-sm font-medium leading-tight text-slate-900">
                {user.full_name}
              </p>
              <p className="max-w-44 truncate text-xs leading-tight text-slate-500">
                {user.roles.length > 0 ? user.roles.join(", ") : user.email}
              </p>
            </div>
          </div>
        )}
        <button
          onClick={logout}
          className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
        >
          Keluar
        </button>
      </div>
    </header>
  );
}
