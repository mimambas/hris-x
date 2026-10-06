"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthContext";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { Spinner } from "@/components/ui";

// Penjaga rute: halaman di dalam (main) hanya untuk pengguna yang sudah masuk.
export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { token, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  if (!ready || !token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-mist">
        <Spinner label="Memeriksa sesi…" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-mist">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <div className="mx-auto w-full max-w-7xl px-6 py-8 lg:px-10">{children}</div>
      </main>
    </div>
  );
}
