"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type { Me, OnboardingProcess, OnboardingTask } from "@/lib/types";
import { tanggal } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  btnSmall,
  btnDanger,
} from "@/components/ui";

const TEAM_LABEL: Record<string, string> = {
  hr: "HR",
  it: "IT",
  ga: "GA",
  manager: "Atasan",
  finance: "Keuangan",
};

const TASK_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "Menunggu", cls: "bg-slate-100 text-slate-700" },
  in_progress: { label: "Dikerjakan", cls: "bg-blue-100 text-blue-700" },
  done: { label: "Selesai", cls: "bg-green-100 text-green-700" },
  skipped: { label: "Dilewati", cls: "bg-amber-100 text-amber-700" },
};

interface DetailResp {
  process: OnboardingProcess;
  tasks: (OnboardingTask & {
    required_doc_type?: string | null;
    doc_ready?: boolean | null;
  })[];
}

export default function OnboardingDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [me, setMe] = useState<Me | null>(null);
  const [data, setData] = useState<DetailResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const isHr = me?.is_hr || me?.is_superadmin;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [meData, detail] = await Promise.all([
        apiFetch<Me>("/me"),
        apiFetch<DetailResp>(`/onboarding/processes/${id}`),
      ]);
      setMe(meData);
      setData(detail);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal memuat detail proses."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function setStatus(task: OnboardingTask, status: string) {
    setBusyId(task.id);
    setActionError(null);
    try {
      await apiFetch(`/onboarding/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await load();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal mengubah status tugas."
      );
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <EmptyState message="Data tidak ditemukan." />;

  const { process, tasks } = data;

  return (
    <div>
      <PageHeader
        title={`${process.kind === "onboarding" ? "Onboarding" : "Offboarding"} — ${process.person_name ?? ""}`}
        subtitle={`${process.template_name ?? ""} · Mulai ${tanggal(process.start_date)}`}
      />
      <Link href="/onboarding" className="mb-4 inline-block text-sm text-brand-700 hover:underline">
        ← Kembali ke daftar
      </Link>

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <Card>
        <div className="mb-4 flex items-center gap-3 text-sm">
          <span className="text-slate-600">
            {process.done_tasks}/{process.total_tasks} tugas selesai
          </span>
          {process.overdue_tasks > 0 && (
            <span className="rounded bg-red-100 px-2 py-0.5 font-semibold text-red-700">
              {process.overdue_tasks} terlambat
            </span>
          )}
        </div>
        {tasks.length === 0 ? (
          <EmptyState message="Belum ada tugas." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {tasks.map((t) => (
              <li key={t.id} className="py-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="font-medium text-slate-900">{t.title}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Tim {TEAM_LABEL[t.team] ?? t.team}
                      {t.assignee_name && ` · ${t.assignee_name}`} · Tenggat{" "}
                      {tanggal(t.due_date)}
                    </p>
                    {t.required_doc_type && (
                      <p className="mt-0.5 text-xs">
                        Butuh dokumen: {t.required_doc_type.toUpperCase()}{" "}
                        {t.doc_ready ? (
                          <span className="font-semibold text-green-700">✓ tersedia</span>
                        ) : (
                          <span className="font-semibold text-amber-700">belum ada</span>
                        )}
                      </p>
                    )}
                    {t.is_overdue && (
                      <p className="mt-0.5 text-xs font-semibold text-red-700">
                        ⚠ Terlambat — perlu eskalasi
                      </p>
                    )}
                  </div>
                  <span
                    className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${TASK_STATUS[t.status].cls}`}
                  >
                    {TASK_STATUS[t.status].label}
                  </span>
                </div>
                {process.status === "in_progress" && (
                  <div className="mt-2 flex gap-2">
                    {t.status === "pending" && (
                      <button
                        className={btnSmall}
                        disabled={busyId === t.id}
                        onClick={() => setStatus(t, "in_progress")}
                      >
                        Mulai
                      </button>
                    )}
                    {t.status !== "done" && (
                      <button
                        className={btnSmall}
                        disabled={busyId === t.id}
                        onClick={() => setStatus(t, "done")}
                      >
                        Selesai
                      </button>
                    )}
                    {t.status !== "skipped" && t.status !== "done" && (
                      <button
                        className={btnSmall}
                        disabled={busyId === t.id}
                        onClick={() => setStatus(t, "skipped")}
                      >
                        Lewati
                      </button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {isHr && process.status === "in_progress" && (
        <p className="mt-4 text-xs text-slate-500">
          Selesaikan atau batalkan proses dari{" "}
          <Link href="/onboarding" className="text-brand-700 hover:underline">
            daftar proses
          </Link>
          .
        </p>
      )}
    </div>
  );
}
