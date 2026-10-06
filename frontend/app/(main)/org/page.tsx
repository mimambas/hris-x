"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { OrgChartNode } from "@/lib/types";
import { tanggal, todayISO } from "@/lib/format";
import { PageHeader, Card, Spinner, ErrorBox, EmptyState } from "@/components/ui";


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
    </div>
  );
}
