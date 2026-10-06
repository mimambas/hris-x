"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggalWaktu } from "@/lib/format";
import { Card, EmptyState, ErrorBox, Spinner, btnSmall } from "@/components/ui";

export interface NotifItem {
  id: string;
  category: string;
  title: string;
  body: string;
  link: string | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

interface NotifList {
  items: NotifItem[];
  unread_count: number;
}

interface PrefItem {
  category: string;
  category_label: string;
  channel: string;
  channel_label: string;
  channel_available: boolean;
  enabled: boolean;
}

const CATEGORY_ICON: Record<string, string> = {
  pengumuman: "📢",
  kudos: "🏅",
  helpdesk: "🎫",
  perubahan_data: "📝",
  persetujuan: "✅",
};

/** Lonceng notifikasi untuk sidebar: badge jumlah belum dibaca. */
export function NotificationBell() {
  const [unread, setUnread] = useState(0);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch<NotifList>("/notifications?limit=1");
      setUnread(r.unread_count);
    } catch {
      /* diam: lonceng hanya indikator */
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 60000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Link
      href="/profil"
      className="relative flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-base shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
      title="Notifikasi saya"
      aria-label="Notifikasi saya"
    >
      <span aria-hidden>🔔</span>
      {unread > 0 && (
        <span className="absolute -right-1 -top-1 rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ring-2 ring-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

/** Daftar notifikasi pengguna + aksi tandai dibaca. */
export function NotificationsPanel() {
  const [data, setData] = useState<NotifList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await apiFetch<NotifList>("/notifications?limit=30"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat notifikasi.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function markRead(n: NotifItem) {
    try {
      await apiFetch(`/notifications/${n.id}/read`, { method: "POST" });
      await load();
    } catch {
      /* abaikan: muat ulang menampilkan keadaan terakhir */
    }
  }

  async function markAll() {
    setBusy(true);
    try {
      await apiFetch("/notifications/read-all", { method: "POST" });
      await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title={`Notifikasi saya${data ? ` (${data.unread_count} belum dibaca)` : ""}`}
    >
      {error ? (
        <ErrorBox message={error} />
      ) : !data ? (
        <Spinner />
      ) : data.items.length === 0 ? (
        <EmptyState message="Belum ada notifikasi. Pengumuman, kudos, dan keputusan HR akan muncul di sini." />
      ) : (
        <>
          {data.unread_count > 0 && (
            <div className="mb-2 text-right">
              <button className={btnSmall} disabled={busy} onClick={() => void markAll()}>
                Tandai semua dibaca
              </button>
            </div>
          )}
          <ul className="divide-y divide-slate-100">
            {data.items.map((n) => (
              <li key={n.id} className={`py-2.5 ${n.is_read ? "opacity-60" : ""}`}>
                <div className="flex items-start gap-2">
                  <span aria-hidden>{CATEGORY_ICON[n.category] ?? "🔔"}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">{n.title}</p>
                    {n.body && (
                      <p className="truncate text-sm text-slate-500">{n.body}</p>
                    )}
                    <p className="text-xs text-slate-400">
                      {tanggalWaktu(n.created_at)}
                      {n.is_read ? " · sudah dibaca" : " · belum dibaca"}
                    </p>
                  </div>
                  {!n.is_read && (
                    <button className={btnSmall} onClick={() => void markRead(n)}>
                      Tandai dibaca
                    </button>
                  )}
                  {n.link && (
                    <Link className={btnSmall} href={n.link}>
                      Buka
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/** Matriks preferensi notifikasi per kategori x kanal. */
export function NotificationPreferences() {
  const [prefs, setPrefs] = useState<PrefItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PrefItem[]>("/notification-preferences")
      .then(setPrefs)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat preferensi.")
      );
  }, []);

  async function toggle(p: PrefItem) {
    const key = `${p.category}:${p.channel}`;
    setSaving(key);
    setNotice(null);
    try {
      const updated = await apiFetch<PrefItem[]>("/notification-preferences", {
        method: "PUT",
        body: JSON.stringify({
          preferences: [
            { category: p.category, channel: p.channel, enabled: !p.enabled },
          ],
        }),
      });
      setPrefs(updated);
      setNotice("Preferensi tersimpan.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan.");
    } finally {
      setSaving(null);
    }
  }

  const categories = prefs
    ? Array.from(new Map(prefs.map((p) => [p.category, p.category_label])).entries())
    : [];

  return (
    <Card title="Preferensi notifikasi">
      <p className="mb-3 text-sm text-slate-500">
        Atur notifikasi apa yang ingin Anda terima. Kanal Email dan WhatsApp
        belum terhubung — pilihan Anda disimpan dan berlaku otomatis saat
        kanal itu aktif.
      </p>
      {notice && (
        <p className="mb-2 text-sm text-emerald-700">{notice}</p>
      )}
      {error ? (
        <ErrorBox message={error} />
      ) : !prefs ? (
        <Spinner />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400">
                <th className="py-1 pr-2 font-medium">Kategori</th>
                {["in_app", "email", "whatsapp"].map((ch) => (
                  <th key={ch} className="px-2 py-1 text-center font-medium">
                    {prefs.find((p) => p.channel === ch)?.channel_label}
                    {ch !== "in_app" && (
                      <span className="block text-[10px] text-amber-600">
                        belum terhubung
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map(([category, label]) => (
                <tr key={category} className="border-t border-slate-100">
                  <td className="py-2 pr-2 text-slate-700">
                    <span aria-hidden className="mr-1">
                      {CATEGORY_ICON[category] ?? "🔔"}
                    </span>
                    {label}
                  </td>
                  {["in_app", "email", "whatsapp"].map((ch) => {
                    const p = prefs.find(
                      (x) => x.category === category && x.channel === ch
                    );
                    if (!p) return <td key={ch} />;
                    const key = `${p.category}:${p.channel}`;
                    return (
                      <td key={ch} className="px-2 py-2 text-center">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-emerald-600"
                          checked={p.enabled}
                          disabled={saving === key}
                          onChange={() => void toggle(p)}
                          aria-label={`${label} via ${p.channel_label}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
