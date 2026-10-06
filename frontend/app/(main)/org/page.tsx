"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { OrgChartNode } from "@/lib/types";
import { tanggal, todayISO } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  Field,
  Modal,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

interface LegalEntityRow {
  id: string;
  name: string;
  npwp: string | null;
}


function TreeNode({ node, depth }: { node: OrgChartNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={`flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 ${
          depth === 0 ? "shadow-sm" : ""
        }`}
        style={{ marginLeft: depth > 0 ? 0 : 0 }}
      >
        {hasChildren ? (
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-100 text-xs font-bold text-slate-600 hover:bg-slate-200"
            aria-label={open ? "Tutup" : "Buka"}
          >
            {open ? "−" : "+"}
          </button>
        ) : (
          <span className="h-6 w-6 shrink-0" />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{node.name}</p>
          <p className="truncate text-xs text-slate-500">{node.legal_entity?.name ?? ""}</p>
        </div>
      </div>
      {hasChildren && open && (
        <ul className="ml-4 space-y-2 border-l-2 border-slate-200 pl-4 pt-2">
          {node.children.map((c) => (
            <TreeNode key={c.id} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function countNodes(nodes: OrgChartNode[]): number {
  return nodes.reduce((n, x) => n + 1 + countNodes(x.children), 0);
}

export default function OrgPage() {
  const [asOf, setAsOf] = useState(todayISO());
  const [tree, setTree] = useState<OrgChartNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [entities, setEntities] = useState<LegalEntityRow[]>([]);
  const [leError, setLeError] = useState<string | null>(null);
  const [npwpTarget, setNpwpTarget] = useState<LegalEntityRow | null>(null);
  const [npwpValue, setNpwpValue] = useState("");
  const [npwpError, setNpwpError] = useState<string | null>(null);
  const [npwpBusy, setNpwpBusy] = useState(false);
  const [leNotice, setLeNotice] = useState<string | null>(null);

  async function loadEntities() {
    try {
      setEntities(await apiFetch<LegalEntityRow[]>("/org/legal-entities"));
    } catch {
      setEntities([]);
    }
  }

  async function submitNpwp() {
    if (!npwpTarget) return;
    const digits = npwpValue.replace(/\D/g, "");
    if (digits.length !== 16) {
      setNpwpError("NPWP badan hukum harus tepat 16 angka.");
      return;
    }
    setNpwpBusy(true);
    setNpwpError(null);
    try {
      await apiFetch(`/org/legal-entities/${npwpTarget.id}/versions`, {
        method: "POST",
        body: JSON.stringify({
          valid_from: todayISO(),
          name: npwpTarget.name,
          npwp: digits,
          event: "org_data_update",
          event_reason: "Pembaruan data",
          reason: "Melengkapi NPWP untuk bukti potong BPA1",
        }),
      });
      setLeNotice(`NPWP ${npwpTarget.name} tersimpan.`);
      setNpwpTarget(null);
      await loadEntities();
    } catch (err) {
      setNpwpError(
        err instanceof ApiError ? err.message : "Gagal menyimpan NPWP."
      );
    } finally {
      setNpwpBusy(false);
    }
  }

  async function load(dateStr: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<OrgChartNode[]>(`/org/chart?as_of=${dateStr}`);
      setTree(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat struktur organisasi.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(asOf);
    void loadEntities();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onDateChange(v: string) {
    setAsOf(v);
    if (v) load(v);
  }

  return (
    <div>
      <PageHeader
        title="Struktur organisasi"
        subtitle="Pohon hierarki unit per tanggal"
        action={
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Per tanggal
            <input
              type="date"
              value={asOf}
              max={todayISO()}
              onChange={(e) => onDateChange(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
        }
      />

      {loading ? (
        <Spinner label="Memuat struktur organisasi…" />
      ) : error ? (
        <ErrorBox message={error} onRetry={() => load(asOf)} />
      ) : tree.length === 0 ? (
        <EmptyState message={`Tidak ada struktur organisasi pada ${tanggal(asOf)}.`} />
      ) : (
        <Card
          title={`${countNodes(tree)} unit`}
          subtitle={`Struktur yang berlaku per ${tanggal(asOf)}`}
        >
          <ul className="space-y-2">
            {tree.map((n) => (
              <TreeNode key={n.id} node={n} depth={0} />
            ))}
          </ul>
        </Card>
      )}

      <div className="mt-4">
        <Card
          title="Badan hukum"
          subtitle="NPWP pemotong dipakai pada bukti potong tahunan (BPA1) dan ekspor XML Coretax."
        >
          {leNotice && (
            <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              {leNotice}
            </div>
          )}
          {leError && <ErrorBox message={leError} />}
          {entities.length === 0 ? (
            <EmptyState message="Tidak ada data badan hukum yang dapat ditampilkan untuk akun Anda." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {entities.map((e) => (
                <li
                  key={e.id}
                  className="flex flex-wrap items-center gap-3 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-800">
                      {e.name}
                    </p>
                    <p className="font-mono text-xs text-slate-500">
                      NPWP: {e.npwp ?? "belum diatur"}
                    </p>
                  </div>
                  <button
                    className={btnSmall}
                    onClick={() => {
                      setNpwpTarget(e);
                      setNpwpValue(e.npwp ?? "");
                      setNpwpError(null);
                    }}
                  >
                    {e.npwp ? "Ubah NPWP" : "Atur NPWP"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {npwpTarget && (
        <Modal
          title={`NPWP — ${npwpTarget.name}`}
          onClose={() => setNpwpTarget(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                onClick={() => setNpwpTarget(null)}
              >
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={npwpBusy}
                onClick={() => void submitNpwp()}
              >
                {npwpBusy ? "Menyimpan…" : "Simpan NPWP"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              NPWP badan hukum (pemotong) 16 angka. Perubahan disimpan
              sebagai versi baru yang berlaku mulai hari ini.
            </p>
            <Field label="NPWP (16 angka)">
              <input
                className={inputCls}
                inputMode="numeric"
                maxLength={20}
                value={npwpValue}
                onChange={(e) => setNpwpValue(e.target.value)}
                placeholder="mis. 1234567890123456"
              />
            </Field>
            {npwpError && <ErrorBox message={npwpError} />}
          </div>
        </Modal>
      )}
    </div>
  );
}
