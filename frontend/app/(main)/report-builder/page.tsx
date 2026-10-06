"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError, getApiBase } from "@/lib/api";
import { getToken } from "@/components/AuthContext";
import {
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  PageHeader,
  Spinner,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

interface RField {
  key: string;
  label: string;
  type: string;
  sensitive: boolean;
}

interface RObject {
  key: string;
  label: string;
  fields: RField[];
}

interface Column {
  key: string;
  label: string;
  type: string;
}

interface RunResult {
  columns: Column[];
  rows: Record<string, unknown>[];
  total_rows: number;
}

interface FilterRow {
  field: string;
  op: string;
  value: string;
  value2: string;
}

interface Definition {
  id: string;
  name: string;
  spec: Record<string, unknown>;
  updated_at: string;
}

interface BiDataset {
  dataset: string;
  label: string;
  sync_field: string | null;
  mode: string;
  url: string;
}

interface BiKey {
  id: string;
  name: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

interface BiKeyCreated extends BiKey {
  token: string;
  token_hint: string;
}

const OPS: { key: string; label: string }[] = [
  { key: "eq", label: "sama dengan" },
  { key: "neq", label: "tidak sama" },
  { key: "contains", label: "mengandung teks" },
  { key: "gt", label: "lebih besar" },
  { key: "gte", label: "minimal" },
  { key: "lt", label: "lebih kecil" },
  { key: "lte", label: "maksimal" },
  { key: "antara", label: "antara (dari–sampai)" },
];

function fmtCell(v: unknown, type: string): string {
  if (v === null || v === undefined) return "—";
  if (type === "num") {
    const n = Number(v);
    return Number.isInteger(n) ? n.toLocaleString("id-ID") : n.toLocaleString("id-ID", { maximumFractionDigits: 2 });
  }
  return String(v);
}

export default function ReportBuilderPage() {
  const [catalog, setCatalog] = useState<RObject[]>([]);
  const [objectKey, setObjectKey] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [groupBy, setGroupBy] = useState("");
  const [aggFn, setAggFn] = useState("count");
  const [aggField, setAggField] = useState("");
  const [sortBy, setSortBy] = useState("");
  const [sortDir, setSortDir] = useState("asc");

  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveName, setSaveName] = useState("");

  // Ekspor BI / data warehouse (ANL-005).
  const [biDatasets, setBiDatasets] = useState<BiDataset[]>([]);
  const [biKeys, setBiKeys] = useState<BiKey[]>([]);
  const [biName, setBiName] = useState("");
  const [biToken, setBiToken] = useState<string | null>(null);
  const [biBusy, setBiBusy] = useState(false);
  const [biError, setBiError] = useState<string | null>(null);

  const loadBi = useCallback(async () => {
    const [ds, ks] = await Promise.all([
      apiFetch<BiDataset[]>("/bi/datasets").catch(() => []),
      apiFetch<BiKey[]>("/bi/keys").catch(() => []),
    ]);
    setBiDatasets(ds);
    setBiKeys(ks);
  }, []);

  useEffect(() => {
    void loadBi();
  }, [loadBi]);

  async function createBiKey() {
    if (!biName.trim()) return;
    setBiBusy(true);
    setBiError(null);
    try {
      const created = await apiFetch<BiKeyCreated>("/bi/keys", {
        method: "POST",
        body: JSON.stringify({ name: biName.trim() }),
      });
      setBiToken(created.token);
      setBiName("");
      await loadBi();
    } catch (err) {
      setBiError(err instanceof ApiError ? err.message : "Gagal membuat kunci BI.");
    } finally {
      setBiBusy(false);
    }
  }

  async function revokeBiKey(k: BiKey) {
    setBiError(null);
    try {
      await apiFetch(`/bi/keys/${k.id}`, { method: "DELETE" });
      await loadBi();
    } catch (err) {
      setBiError(err instanceof ApiError ? err.message : "Gagal mencabut kunci.");
    }
  }

  async function downloadBiCsv(d: BiDataset) {
    try {
      const base = getApiBase();
      const res = await fetch(
        `${base}/bi/exports/${d.dataset}?format=csv&limit=1000`,
        { headers: { Authorization: `Bearer ${getToken() ?? ""}` } }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bi-${d.dataset}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setBiError("Gagal mengunduh CSV dataset.");
    }
  }

  const currentObject = useMemo(
    () => catalog.find((o) => o.key === objectKey) ?? null,
    [catalog, objectKey]
  );
  const numericFields = useMemo(
    () => (currentObject?.fields ?? []).filter((f) => f.type === "num"),
    [currentObject]
  );

  const loadDefinitions = useCallback(async () => {
    try {
      setDefinitions(await apiFetch<Definition[]>("/report-definitions"));
    } catch {
      setDefinitions([]);
    }
  }, []);

  useEffect(() => {
    apiFetch<RObject[]>("/report-builder/catalog")
      .then((rows) => {
        setCatalog(rows);
        if (rows[0]) {
          setObjectKey(rows[0].key);
          setSelected(rows[0].fields.slice(0, 3).map((f) => f.key));
        }
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Gagal memuat katalog.")
      )
      .finally(() => setLoadingCatalog(false));
    void loadDefinitions();
  }, [loadDefinitions]);

  function buildSpec(): Record<string, unknown> | null {
    if (!objectKey || selected.length === 0) {
      setError("Pilih objek dan minimal satu field.");
      return null;
    }
    const specFilters = filters
      .filter((f) => f.field && f.value !== "")
      .map((f) => ({
        field: f.field,
        op: f.op,
        value:
          f.op === "antara" ? [f.value, f.value2] : f.value,
      }));
    const spec: Record<string, unknown> = {
      object: objectKey,
      fields: selected,
      filters: specFilters,
      limit: 500,
    };
    if (groupBy) {
      spec.group_by = groupBy;
      spec.aggregate_fn = aggFn;
      if (aggFn !== "count") spec.aggregate_field = aggField || null;
    } else if (sortBy) {
      spec.sort_by = sortBy;
      spec.sort_dir = sortDir;
    }
    return spec;
  }

  async function run() {
    const spec = buildSpec();
    if (!spec) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await apiFetch<RunResult>("/report-builder/run", {
        method: "POST",
        body: JSON.stringify(spec),
      }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menjalankan laporan.");
    } finally {
      setRunning(false);
    }
  }

  async function exportXlsx() {
    const spec = buildSpec();
    if (!spec) return;
    setExporting(true);
    setError(null);
    try {
      const token = getToken();
      const res = await fetch(`${getApiBase()}/report-builder/export.xlsx`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(spec),
      });
      if (!res.ok) throw new Error("ekspor gagal");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `laporan-${objectKey}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice("Berkas XLSX terunduh.");
    } catch {
      setError("Gagal mengekspor XLSX.");
    } finally {
      setExporting(false);
    }
  }

  async function saveDefinition() {
    const spec = buildSpec();
    if (!spec || !saveName.trim()) return;
    try {
      await apiFetch("/report-definitions", {
        method: "POST",
        body: JSON.stringify({ name: saveName.trim(), spec }),
      });
      setNotice(`Definisi "${saveName.trim()}" tersimpan.`);
      setSaving(false);
      setSaveName("");
      await loadDefinitions();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menyimpan.");
    }
  }

  async function runDefinition(d: Definition) {
    setRunning(true);
    setError(null);
    try {
      setResult(
        await apiFetch<RunResult>(`/report-definitions/${d.id}/run`, {
          method: "POST",
        })
      );
      setNotice(`Menjalankan definisi "${d.name}".`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menjalankan definisi.");
    } finally {
      setRunning(false);
    }
  }

  async function deleteDefinition(d: Definition) {
    try {
      await apiFetch(`/report-definitions/${d.id}`, { method: "DELETE" });
      await loadDefinitions();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal menghapus.");
    }
  }

  function applyDefinition(d: Definition) {
    const spec = d.spec as {
      object?: string;
      fields?: string[];
      group_by?: string | null;
      aggregate_fn?: string | null;
      aggregate_field?: string | null;
      sort_by?: string | null;
      sort_dir?: string;
      filters?: { field: string; op: string; value: unknown }[];
    };
    if (spec.object) setObjectKey(spec.object);
    setSelected(spec.fields ?? []);
    setGroupBy(spec.group_by ?? "");
    setAggFn(spec.aggregate_fn ?? "count");
    setAggField(spec.aggregate_field ?? "");
    setSortBy(spec.sort_by ?? "");
    setSortDir(spec.sort_dir ?? "asc");
    setFilters(
      (spec.filters ?? []).map((f) => ({
        field: f.field,
        op: f.op,
        value: Array.isArray(f.value) ? String(f.value[0] ?? "") : String(f.value ?? ""),
        value2: Array.isArray(f.value) ? String(f.value[1] ?? "") : "",
      }))
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Report Builder"
        subtitle="Susun laporan sendiri dari objek data terkurasi. Field yang tidak Anda miliki izinnya tidak muncul dan tidak bisa dipilih. Jadwal kirim berkala menyusul setelah kanal email tersedia."
      />

      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {error && <ErrorBox message={error} />}

      {loadingCatalog ? (
        <Spinner />
      ) : catalog.length === 0 ? (
        <Card title="Belum ada objek yang tersedia">
          <EmptyState message="Peran Anda belum memiliki izin melihat objek laporan mana pun. Minta HR menambahkan izin view pada objek terkait." />
        </Card>
      ) : (
        <>
          <Card title="Susun laporan">
            <div className="space-y-4">
              <Field label="Objek data">
                <select
                  className={inputCls}
                  value={objectKey}
                  onChange={(e) => {
                    const obj = catalog.find((o) => o.key === e.target.value);
                    setObjectKey(e.target.value);
                    setSelected(obj ? obj.fields.slice(0, 3).map((f) => f.key) : []);
                    setFilters([]);
                    setGroupBy("");
                    setResult(null);
                  }}
                >
                  {catalog.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Field yang ditampilkan">
                <div className="flex flex-wrap gap-2">
                  {(currentObject?.fields ?? []).map((f) => {
                    const active = selected.includes(f.key);
                    return (
                      <button
                        key={f.key}
                        type="button"
                        onClick={() =>
                          setSelected((prev) =>
                            active
                              ? prev.filter((k) => k !== f.key)
                              : [...prev, f.key]
                          )
                        }
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${
                          active
                            ? "border-emerald-600 bg-emerald-600 text-white"
                            : "border-slate-300 bg-white text-slate-600"
                        }`}
                      >
                        {f.label}
                        {f.sensitive ? " 🔒" : ""}
                      </button>
                    );
                  })}
                </div>
              </Field>

              <div>
                <p className="mb-1 text-sm font-medium text-slate-700">
                  Filter
                </p>
                <div className="space-y-2">
                  {filters.map((f, i) => (
                    <div key={i} className="flex flex-wrap items-end gap-2">
                      <div className="min-w-40 flex-1">
                        <Field label="Field">
                          <select
                            className={inputCls}
                            value={f.field}
                            onChange={(e) =>
                              setFilters((prev) =>
                                prev.map((x, j) =>
                                  j === i ? { ...x, field: e.target.value } : x
                                )
                              )
                            }
                          >
                            <option value="">Pilih field…</option>
                            {(currentObject?.fields ?? []).map((x) => (
                              <option key={x.key} value={x.key}>
                                {x.label}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      <div className="min-w-36">
                        <Field label="Operator">
                          <select
                            className={inputCls}
                            value={f.op}
                            onChange={(e) =>
                              setFilters((prev) =>
                                prev.map((x, j) =>
                                  j === i ? { ...x, op: e.target.value } : x
                                )
                              )
                            }
                          >
                            {OPS.map((o) => (
                              <option key={o.key} value={o.key}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      <div className="min-w-36 flex-1">
                        <Field label="Nilai">
                          <input
                            className={inputCls}
                            value={f.value}
                            onChange={(e) =>
                              setFilters((prev) =>
                                prev.map((x, j) =>
                                  j === i ? { ...x, value: e.target.value } : x
                                )
                              )
                            }
                          />
                        </Field>
                      </div>
                      {f.op === "antara" && (
                        <div className="min-w-36 flex-1">
                          <Field label="Sampai">
                            <input
                              className={inputCls}
                              value={f.value2}
                              onChange={(e) =>
                                setFilters((prev) =>
                                  prev.map((x, j) =>
                                    j === i ? { ...x, value2: e.target.value } : x
                                  )
                                )
                              }
                            />
                          </Field>
                        </div>
                      )}
                      <button
                        className={btnSmall}
                        onClick={() =>
                          setFilters((prev) => prev.filter((_, j) => j !== i))
                        }
                      >
                        Hapus
                      </button>
                    </div>
                  ))}
                  <button
                    className={btnSecondary}
                    onClick={() =>
                      setFilters((prev) => [
                        ...prev,
                        { field: "", op: "eq", value: "", value2: "" },
                      ])
                    }
                  >
                    + Tambah filter
                  </button>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Kelompokkan berdasarkan (opsional)">
                  <select
                    className={inputCls}
                    value={groupBy}
                    onChange={(e) => setGroupBy(e.target.value)}
                  >
                    <option value="">Tanpa pengelompokan</option>
                    {(currentObject?.fields ?? []).map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </Field>
                {groupBy && (
                  <>
                    <Field label="Agregasi">
                      <select
                        className={inputCls}
                        value={aggFn}
                        onChange={(e) => setAggFn(e.target.value)}
                      >
                        <option value="count">Jumlah baris</option>
                        <option value="sum">SUM</option>
                        <option value="avg">AVG (rata-rata)</option>
                        <option value="min">MIN</option>
                        <option value="max">MAX</option>
                      </select>
                    </Field>
                    {aggFn !== "count" && (
                      <Field label="Field agregasi (numerik)">
                        <select
                          className={inputCls}
                          value={aggField}
                          onChange={(e) => setAggField(e.target.value)}
                        >
                          <option value="">Pilih field…</option>
                          {numericFields.map((f) => (
                            <option key={f.key} value={f.key}>
                              {f.label}
                            </option>
                          ))}
                        </select>
                      </Field>
                    )}
                  </>
                )}
                {!groupBy && (
                  <>
                    <Field label="Urutkan berdasarkan">
                      <select
                        className={inputCls}
                        value={sortBy}
                        onChange={(e) => setSortBy(e.target.value)}
                      >
                        <option value="">Bawaan</option>
                        {(currentObject?.fields ?? []).map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Arah">
                      <select
                        className={inputCls}
                        value={sortDir}
                        onChange={(e) => setSortDir(e.target.value)}
                      >
                        <option value="asc">Naik (A→Z)</option>
                        <option value="desc">Turun (Z→A)</option>
                      </select>
                    </Field>
                  </>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                <button className={btnPrimary} disabled={running} onClick={() => void run()}>
                  {running ? "Menjalankan…" : "Jalankan laporan"}
                </button>
                <button className={btnSecondary} disabled={exporting} onClick={() => void exportXlsx()}>
                  {exporting ? "Mengekspor…" : "Ekspor XLSX"}
                </button>
                <button className={btnSecondary} onClick={() => setSaving(true)}>
                  Simpan definisi
                </button>
              </div>
            </div>
          </Card>

          {result && (
            <Card title={`Hasil (${result.total_rows} baris)`}>
              {result.rows.length === 0 ? (
                <EmptyState message="Tidak ada baris yang cocok dengan susunan laporan ini." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-slate-400">
                        {result.columns.map((c) => (
                          <th key={c.key} className="py-1 pr-3 font-medium">
                            {c.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i} className="border-t border-slate-100">
                          {result.columns.map((c) => (
                            <td key={c.key} className="py-1.5 pr-3 text-slate-700">
                              {fmtCell(row[c.key], c.type)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}

          <Card title={`Definisi tersimpan saya (${definitions.length})`}>
            {definitions.length === 0 ? (
              <EmptyState message="Belum ada definisi tersimpan. Susun laporan lalu klik Simpan definisi." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {definitions.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-2 py-2">
                    <p className="flex-1 text-sm font-medium text-slate-800">
                      {d.name}
                    </p>
                    <button className={btnSmall} onClick={() => applyDefinition(d)}>
                      Muat ke penyusun
                    </button>
                    <button className={btnPrimary} disabled={running} onClick={() => void runDefinition(d)}>
                      Jalankan
                    </button>
                    <button className={btnSmall} onClick={() => void deleteDefinition(d)}>
                      Hapus
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card
            title="Ekspor BI / Data Warehouse (ANL-005)"
            subtitle="API tarik inkremental untuk Metabase, Looker Studio, Google Sheets, atau skrip ETL Anda."
          >
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                Dataset sama dengan objek report builder di atas dan selalu
                menghormati izin RBP serta populasi Anda. Sinkron harian:
                panggil URL dataset dengan parameter <code>since</code>{" "}
                (tanggal/periode terakhir yang Anda simpan), lalu lakukan
                upsert berdasarkan <code>employment_id</code> + penanda.
                Karyawan adalah snapshot penuh (upsert berdasarkan nik).
              </p>
              {biError && <ErrorBox message={biError} />}

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400">
                      <th className="py-1 pr-3 font-medium">Dataset</th>
                      <th className="py-1 pr-3 font-medium">Mode</th>
                      <th className="py-1 pr-3 font-medium">URL ekspor</th>
                      <th className="py-1 pr-3 font-medium">Contoh</th>
                    </tr>
                  </thead>
                  <tbody>
                    {biDatasets.map((d) => (
                      <tr key={d.dataset} className="border-t border-slate-100">
                        <td className="py-1.5 pr-3 font-medium text-slate-800">
                          {d.label}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-600">
                          {d.mode}
                          {d.sync_field ? ` · since: ${d.sync_field}` : ""}
                        </td>
                        <td className="py-1.5 pr-3 font-mono text-xs text-slate-600">
                          GET {d.url}
                          {d.sync_field ? `?since=2026-01-01` : ""}
                        </td>
                        <td className="py-1.5 pr-3">
                          <button className={btnSmall} onClick={() => void downloadBiCsv(d)}>
                            Unduh CSV
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="border-t border-slate-100 pt-3">
                <p className="mb-2 text-sm font-medium text-slate-800">
                  Kunci API BI saya
                </p>
                <p className="mb-3 text-xs text-slate-500">
                  Alat eksternal memakai header{" "}
                  <code>X-BI-Key: &lt;token&gt;</code> alih-alih login Anda.
                  Token hanya ditampilkan satu kali saat dibuat; yang
                  tersimpan di server hanya hash-nya. Cabut kunci bila
                  tidak dipakai lagi.
                </p>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <input
                    className={`${inputCls} max-w-xs`}
                    placeholder="Nama kunci, mis. Metabase kantor"
                    maxLength={120}
                    value={biName}
                    onChange={(e) => setBiName(e.target.value)}
                  />
                  <button
                    className={btnPrimary}
                    disabled={biBusy || !biName.trim()}
                    onClick={() => void createBiKey()}
                  >
                    {biBusy ? "Membuat…" : "Buat kunci"}
                  </button>
                </div>
                {biToken && (
                  <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
                    <p className="mb-1 text-xs font-semibold text-amber-800">
                      Simpan token ini sekarang — tidak akan ditampilkan lagi:
                    </p>
                    <p className="break-all font-mono text-xs text-amber-900">
                      {biToken}
                    </p>
                  </div>
                )}
                {biKeys.length === 0 ? (
                  <EmptyState message="Belum ada kunci API BI." />
                ) : (
                  <ul className="divide-y divide-slate-100">
                    {biKeys.map((k) => (
                      <li key={k.id} className="flex flex-wrap items-center gap-2 py-2">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800">
                            {k.name}
                          </p>
                          <p className="text-xs text-slate-500">
                            Dibuat{" "}
                            {new Date(k.created_at).toLocaleDateString("id-ID")}
                            {k.last_used_at
                              ? ` · terakhir dipakai ${new Date(k.last_used_at).toLocaleDateString("id-ID")}`
                              : " · belum pernah dipakai"}
                            {k.revoked_at ? " · sudah dicabut" : " · aktif"}
                          </p>
                        </div>
                        {!k.revoked_at && (
                          <button className={btnSmall} onClick={() => void revokeBiKey(k)}>
                            Cabut
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </Card>
        </>
      )}

      {saving && (
        <Modal
          title="Simpan definisi laporan"
          onClose={() => setSaving(false)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setSaving(false)}>
                Batal
              </button>
              <button className={btnPrimary} disabled={!saveName.trim()} onClick={() => void saveDefinition()}>
                Simpan
              </button>
            </>
          }
        >
          <Field label="Nama definisi">
            <input
              className={inputCls}
              maxLength={120}
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="cth. Karyawan aktif per unit"
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
