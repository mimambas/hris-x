"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  Me,
  OnboardingProcess,
  OnboardingTask,
  OnboardingTemplate,
  Person,
} from "@/lib/types";
import { tanggal } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  Field,
  Modal,
  inputCls,
  btnPrimary,
  btnSecondary,
  btnDanger,
  btnSmall,
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

const PROC_STATUS: Record<string, { label: string; cls: string }> = {
  in_progress: { label: "Berjalan", cls: "bg-blue-100 text-blue-700" },
  completed: { label: "Selesai", cls: "bg-green-100 text-green-700" },
  cancelled: { label: "Dibatalkan", cls: "bg-slate-100 text-slate-500" },
};

type Tab = "tugas" | "proses" | "template";

export default function OnboardingPage() {
  const [tab, setTab] = useState<Tab>("tugas");
  const [me, setMe] = useState<Me | null>(null);
  const [myTasks, setMyTasks] = useState<OnboardingTask[]>([]);
  const [processes, setProcesses] = useState<OnboardingProcess[]>([]);
  const [templates, setTemplates] = useState<OnboardingTemplate[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Filter proses
  const [filterKind, setFilterKind] = useState("");
  const [filterStatus, setFilterStatus] = useState("in_progress");

  // Modal mulai proses (HR)
  const [showStart, setShowStart] = useState(false);
  const [startPerson, setStartPerson] = useState("");
  const [startTemplate, setStartTemplate] = useState("");
  const [startDate, setStartDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [startKind, setStartKind] = useState<"onboarding" | "offboarding">(
    "onboarding"
  );
  const [formError, setFormError] = useState<string | null>(null);

  // Modal template baru (HR)
  const [showTemplate, setShowTemplate] = useState(false);
  const [tplName, setTplName] = useState("");
  const [tplKind, setTplKind] = useState<"onboarding" | "offboarding">(
    "onboarding"
  );

  const isHr = me?.is_hr || me?.is_superadmin;

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const meData = await apiFetch<Me>("/me");
      setMe(meData);
      const params = new URLSearchParams();
      if (filterStatus) params.set("status", filterStatus);
      if (filterKind) params.set("kind", filterKind);
      const qs = params.toString();
      const [tasks, procs] = await Promise.all([
        apiFetch<OnboardingTask[]>("/onboarding/my-tasks"),
        apiFetch<OnboardingProcess[]>(
          `/onboarding/processes${qs ? `?${qs}` : ""}`
        ),
      ]);
      setMyTasks(tasks);
      setProcesses(procs);
      if (meData.is_hr || meData.is_superadmin) {
        const [tpls, ps] = await Promise.all([
          apiFetch<OnboardingTemplate[]>("/onboarding/templates"),
          apiFetch<Person[]>("/persons"),
        ]);
        setTemplates(tpls);
        setPersons(ps);
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal memuat data onboarding."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKind, filterStatus]);

  async function updateTaskStatus(task: OnboardingTask, status: string) {
    setBusyId(task.id);
    setActionError(null);
    setSuccessMsg(null);
    try {
      await apiFetch(`/onboarding/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setSuccessMsg(`Tugas "${task.title}" ditandai ${TASK_STATUS[status].label.toLowerCase()}.`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal mengubah tugas.");
    } finally {
      setBusyId(null);
    }
  }

  async function submitStart() {
    setFormError(null);
    if (!startPerson) return setFormError("Pilih karyawan.");
    if (!startTemplate) return setFormError("Pilih template.");
    if (!startDate) return setFormError("Tanggal mulai wajib diisi.");
    setBusyId("start");
    try {
      await apiFetch("/onboarding/processes", {
        method: "POST",
        body: JSON.stringify({
          person_id: startPerson,
          template_id: startTemplate,
          start_date: startDate,
        }),
      });
      setShowStart(false);
      setSuccessMsg("Proses berhasil dimulai.");
      setTab("proses");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal memulai proses.");
    } finally {
      setBusyId(null);
    }
  }

  async function submitTemplate() {
    setFormError(null);
    if (!tplName.trim()) return setFormError("Nama template wajib diisi.");
    setBusyId("tpl");
    try {
      await apiFetch("/onboarding/templates", {
        method: "POST",
        body: JSON.stringify({ name: tplName.trim(), kind: tplKind }),
      });
      setShowTemplate(false);
      setTplName("");
      setSuccessMsg("Template berhasil dibuat.");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Gagal membuat template.");
    } finally {
      setBusyId(null);
    }
  }

  async function completeProcess(p: OnboardingProcess) {
    setBusyId(p.id);
    setActionError(null);
    try {
      await apiFetch(`/onboarding/processes/${p.id}/complete`, { method: "POST" });
      setSuccessMsg(`Proses ${p.person_name} selesai.`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Gagal menyelesaikan proses.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;

  const tabs: { id: Tab; label: string }[] = [
    { id: "tugas", label: `Tugas Saya${myTasks.length ? ` (${myTasks.length})` : ""}` },
    { id: "proses", label: "Proses" },
    ...(isHr ? [{ id: "template" as Tab, label: "Template" }] : []),
  ];

  return (
    <div>
      <PageHeader
        title="Onboarding & Offboarding"
        subtitle="Checklist karyawan baru dan karyawan keluar lintas tim"
      />

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}
      {successMsg && (
        <div className="mb-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">
          {successMsg}
        </div>
      )}

      <div className="mb-4 flex gap-2 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "tugas" && (
        <Card>
          {myTasks.length === 0 ? (
            <EmptyState message="Tidak ada tugas yang ditugaskan kepada Anda." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {myTasks.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-4 py-3">
                  <div>
                    <p className="font-medium text-slate-900">{t.title}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Tim {TEAM_LABEL[t.team] ?? t.team} · Tenggat{" "}
                      {tanggal(t.due_date)}
                      {t.is_overdue && (
                        <span className="ml-2 rounded bg-red-100 px-2 py-0.5 font-semibold text-red-700">
                          Terlambat
                        </span>
                      )}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {t.status === "pending" && (
                      <button
                        className={btnSmall}
                        disabled={busyId === t.id}
                        onClick={() => updateTaskStatus(t, "in_progress")}
                      >
                        Mulai
                      </button>
                    )}
                    <button
                      className={btnSmall}
                      disabled={busyId === t.id}
                      onClick={() => updateTaskStatus(t, "done")}
                    >
                      Selesai
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "proses" && (
        <div>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <select
              className={inputCls}
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
            >
              <option value="">Semua status</option>
              <option value="in_progress">Berjalan</option>
              <option value="completed">Selesai</option>
              <option value="cancelled">Dibatalkan</option>
            </select>
            <select
              className={inputCls}
              value={filterKind}
              onChange={(e) => setFilterKind(e.target.value)}
            >
              <option value="">Onboarding + Offboarding</option>
              <option value="onboarding">Onboarding</option>
              <option value="offboarding">Offboarding</option>
            </select>
            {isHr && (
              <button className={btnPrimary} onClick={() => setShowStart(true)}>
                + Mulai Proses
              </button>
            )}
          </div>
          {processes.length === 0 ? (
            <Card>
              <EmptyState message="Belum ada proses." />
            </Card>
          ) : (
            <div className="grid gap-3">
              {processes.map((p) => (
                <Card key={p.id}>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <Link
                        href={`/onboarding/${p.id}`}
                        className="font-semibold text-brand-700 hover:underline"
                      >
                        {p.person_name ?? "Karyawan"} —{" "}
                        {p.kind === "onboarding" ? "Onboarding" : "Offboarding"}
                      </Link>
                      <p className="mt-1 text-xs text-slate-500">
                        {p.template_name} · Mulai {tanggal(p.start_date)}
                        {p.target_date && ` · Target ${tanggal(p.target_date)}`}
                      </p>
                      <div className="mt-2 flex items-center gap-2 text-xs">
                        <span
                          className={`rounded px-2 py-0.5 font-medium ${PROC_STATUS[p.status].cls}`}
                        >
                          {PROC_STATUS[p.status].label}
                        </span>
                        <span className="text-slate-600">
                          {p.done_tasks}/{p.total_tasks} tugas selesai
                        </span>
                        {p.overdue_tasks > 0 && (
                          <span className="rounded bg-red-100 px-2 py-0.5 font-semibold text-red-700">
                            {p.overdue_tasks} terlambat
                          </span>
                        )}
                      </div>
                      <div className="mt-2 h-1.5 w-48 overflow-hidden rounded bg-slate-100">
                        <div
                          className="h-full bg-brand-600"
                          style={{
                            width: `${
                              p.total_tasks
                                ? Math.round((p.done_tasks / p.total_tasks) * 100)
                                : 0
                            }%`,
                          }}
                        />
                      </div>
                    </div>
                    {isHr && p.status === "in_progress" && (
                      <button
                        className={btnSmall}
                        disabled={busyId === p.id}
                        onClick={() => completeProcess(p)}
                      >
                        Selesaikan
                      </button>
                    )}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "template" && isHr && (
        <div>
          <div className="mb-4">
            <button className={btnPrimary} onClick={() => setShowTemplate(true)}>
              + Template Baru
            </button>
          </div>
          {templates.length === 0 ? (
            <Card>
              <EmptyState message="Belum ada template. Buat template onboarding dan offboarding di sini." />
            </Card>
          ) : (
            <div className="grid gap-3">
              {templates.map((t) => (
                <Card key={t.id}>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-slate-900">{t.name}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {t.kind === "onboarding" ? "Onboarding" : "Offboarding"} ·{" "}
                        {t.task_count} tugas ·{" "}
                        {t.is_active ? "Aktif" : "Nonaktif"}
                      </p>
                    </div>
                    <Link href={`/onboarding/template/${t.id}`} className={btnSmall}>
                      Kelola Tugas
                    </Link>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {showStart && (
        <Modal
          title="Mulai Proses Baru"
          onClose={() => setShowStart(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowStart(false)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === "start"}
                onClick={submitStart}
              >
                Mulai
              </button>
            </>
          }
        >
          {formError && (
            <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              {formError}
            </p>
          )}
          <Field label="Karyawan">
            <select
              className={inputCls}
              value={startPerson}
              onChange={(e) => setStartPerson(e.target.value)}
            >
              <option value="">— Pilih —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Jenis">
            <select
              className={inputCls}
              value={startKind}
              onChange={(e) => {
                setStartKind(e.target.value as "onboarding" | "offboarding");
                setStartTemplate("");
              }}
            >
              <option value="onboarding">Onboarding</option>
              <option value="offboarding">Offboarding</option>
            </select>
          </Field>
          <Field label="Template">
            <select
              className={inputCls}
              value={startTemplate}
              onChange={(e) => setStartTemplate(e.target.value)}
            >
              <option value="">— Pilih —</option>
              {templates
                .filter((t) => t.kind === startKind && t.is_active)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.task_count} tugas)
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Tanggal mulai">
            <input
              type="date"
              className={inputCls}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {showTemplate && (
        <Modal
          title="Template Baru"
          onClose={() => setShowTemplate(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowTemplate(false)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={busyId === "tpl"}
                onClick={submitTemplate}
              >
                Simpan
              </button>
            </>
          }
        >
          {formError && (
            <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
              {formError}
            </p>
          )}
          <Field label="Nama template">
            <input
              className={inputCls}
              value={tplName}
              onChange={(e) => setTplName(e.target.value)}
              placeholder="mis. Orientasi Karyawan Baru"
            />
          </Field>
          <Field label="Jenis">
            <select
              className={inputCls}
              value={tplKind}
              onChange={(e) =>
                setTplKind(e.target.value as "onboarding" | "offboarding")
              }
            >
              <option value="onboarding">Onboarding</option>
              <option value="offboarding">Offboarding</option>
            </select>
          </Field>
        </Modal>
      )}
    </div>
  );
}
