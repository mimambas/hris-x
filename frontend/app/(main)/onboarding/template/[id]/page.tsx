"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import type { OnboardingTemplateDetail } from "@/lib/types";
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

export default function TemplateDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [data, setData] = useState<OnboardingTemplateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [busy, setBusy] = useState(false);

  const [title, setTitle] = useState("");
  const [team, setTeam] = useState("hr");
  const [offset, setOffset] = useState("0");
  const [docType, setDocType] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const d = await apiFetch<OnboardingTemplateDetail>(
        `/onboarding/templates/${id}`
      );
      setData(d);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal memuat template."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function submitAdd() {
    setFormError(null);
    if (!title.trim()) return setFormError("Judul tugas wajib diisi.");
    const off = parseInt(offset, 10);
    if (Number.isNaN(off)) return setFormError("Offset hari harus angka.");
    setBusy(true);
    try {
      await apiFetch(`/onboarding/templates/${id}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          team,
          due_offset_days: off,
          sort_order: data?.tasks.length ?? 0,
          required_doc_type: docType.trim() || null,
        }),
      });
      setShowAdd(false);
      setTitle("");
      setOffset("0");
      setDocType("");
      await load();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Gagal menambah tugas."
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeTask(taskId: string) {
    setActionError(null);
    try {
      await apiFetch(`/onboarding/templates/${id}/tasks/${taskId}`, {
        method: "DELETE",
      });
      await load();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal menghapus tugas."
      );
    }
  }

  if (loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <EmptyState message="Template tidak ditemukan." />;

  return (
    <div>
      <PageHeader
        title={data.template.name}
        subtitle={`${data.template.kind === "onboarding" ? "Onboarding" : "Offboarding"} · ${data.tasks.length} tugas`}
      />
      <Link href="/onboarding" className="mb-4 inline-block text-sm text-brand-700 hover:underline">
        ← Kembali
      </Link>

      {actionError && (
        <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <div className="mb-4">
        <button className={btnPrimary} onClick={() => setShowAdd(true)}>
          + Tambah Tugas
        </button>
      </div>

      <Card>
        {data.tasks.length === 0 ? (
          <EmptyState message="Belum ada tugas di template ini." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.tasks.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-4 py-3">
                <div>
                  <p className="font-medium text-slate-900">{t.title}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Tim {TEAM_LABEL[t.team] ?? t.team} ·{" "}
                    {t.due_offset_days === 0
                      ? "Hari pertama"
                      : t.due_offset_days > 0
                        ? `H+${t.due_offset_days}`
                        : `H${t.due_offset_days}`}
                    {t.required_doc_type &&
                      ` · Dokumen: ${t.required_doc_type.toUpperCase()}`}
                  </p>
                </div>
                <button className={btnDanger} onClick={() => removeTask(t.id)}>
                  Hapus
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {showAdd && (
        <Modal
          title="Tambah Tugas Template"
          onClose={() => setShowAdd(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setShowAdd(false)}>
                Batal
              </button>
              <button className={btnPrimary} disabled={busy} onClick={submitAdd}>
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
          <Field label="Judul tugas">
            <input
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="mis. Siapkan laptop & akun email"
            />
          </Field>
          <Field label="Tim pelaksana">
            <select
              className={inputCls}
              value={team}
              onChange={(e) => setTeam(e.target.value)}
            >
              <option value="hr">HR</option>
              <option value="it">IT</option>
              <option value="ga">GA</option>
              <option value="manager">Atasan</option>
              <option value="finance">Keuangan</option>
            </select>
          </Field>
          <Field label="Tenggat (hari relatif, negatif = sebelum hari pertama)">
            <input
              type="number"
              className={inputCls}
              value={offset}
              onChange={(e) => setOffset(e.target.value)}
            />
          </Field>
          <Field label="Syarat dokumen (opsional, mis. ktp)">
            <input
              className={inputCls}
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              placeholder="kosongkan bila tidak ada"
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
