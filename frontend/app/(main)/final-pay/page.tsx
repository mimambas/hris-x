"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type {
  PayFinal,
  PayFinalBracket,
  PayFinalCandidate,
  PayFinalConfig,
  PayFinalPreview,
  PayFinalReasonFactor,
} from "@/lib/types";
import { rupiah, tanggal } from "@/lib/format";
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

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  draft: { label: "Draf", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
  finalized: { label: "Final", cls: "bg-blue-100 text-blue-800 ring-blue-300" },
  paid: { label: "Dibayar", cls: "bg-emerald-100 text-emerald-800 ring-emerald-300" },
};

function StatusPill({ status }: { status: string }) {
  const s = STATUS_LABEL[status] ?? { label: status, cls: "bg-slate-100 text-slate-700 ring-slate-300" };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}>
      {s.label}
    </span>
  );
}

function BreakdownRows({ fp }: { fp: PayFinal | PayFinalPreview }) {
  const b = fp.breakdown;
  const rows: [string, string][] = [
    ["Upah sebulan (gaji pokok + tunjangan tetap)", rupiah(fp.monthly_wage)],
    ["Masa kerja", `${fp.years_of_service.toLocaleString("id-ID")} tahun`],
    [`Sisa gaji (${b.hari_kerja_terpakai}/${b.hari_kerja_sebulan} hari kerja)`, rupiah(b.sisa_gaji)],
  ];
  if (b.kompensasi_pkwt > 0) {
    rows.push(["Kompensasi PKWT (masa kerja/12 × upah)", rupiah(b.kompensasi_pkwt)]);
  } else {
    rows.push([
      `Pesangon (${b.pesangon_bulan} bulan × faktor ${b.pesangon_faktor})`,
      rupiah(b.pesangon),
    ]);
    rows.push([
      `UPMK (${b.upmk_bulan} bulan × faktor ${b.upmk_faktor})`,
      rupiah(b.upmk),
    ]);
  }
  rows.push([
    b.uph_termasuk
      ? `UPH: sisa cuti ${b.sisa_cuti_hari} hari × upah/25`
      : "UPH: sisa cuti (tidak termasuk)",
    rupiah(b.sisa_cuti),
  ]);
  for (const adj of b.adjustments ?? []) {
    rows.push([`Penyesuaian: ${adj.label}`, rupiah(adj.amount)]);
  }
  return (
    <div className="overflow-hidden rounded-xl ring-1 ring-slate-200">
      <table className="min-w-full divide-y divide-slate-100 text-sm">
        <tbody className="divide-y divide-slate-100">
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="px-4 py-2.5 text-slate-600">{k}</td>
              <td className="px-4 py-2.5 text-right font-medium text-slate-900">{v}</td>
            </tr>
          ))}
          <tr className="bg-slate-50">
            <td className="px-4 py-2.5 font-medium text-slate-700">Total bruto</td>
            <td className="px-4 py-2.5 text-right font-semibold text-slate-900">{rupiah(fp.gross_total)}</td>
          </tr>
          <tr>
            <td className="px-4 py-2.5 text-slate-600">Potongan sisa pinjaman</td>
            <td className="px-4 py-2.5 text-right font-medium text-slate-900">−{rupiah(fp.loan_deduction)}</td>
          </tr>
          <tr>
            <td className="px-4 py-2.5 text-slate-600">PPh 21 final (pesangon dibayar sekaligus)</td>
            <td className="px-4 py-2.5 text-right font-medium text-slate-900">−{rupiah(fp.tax_amount)}</td>
          </tr>
          <tr className="bg-brand-50">
            <td className="px-4 py-2.5 font-semibold text-brand-900">Dibayarkan (neto)</td>
            <td className="px-4 py-2.5 text-right font-bold text-brand-900">{rupiah(fp.net_amount)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editor konfigurasi tabel (bracket + faktor per alasan)
// ---------------------------------------------------------------------------
type BracketRow = { component: string; min_years: string; max_years: string; months: string };
type FactorRow = {
  reason: string; pesangon_factor: string; upmk_factor: string;
  uph_included: boolean; pkwt_compensation: boolean;
};

function ConfigEditor({ config, onSaved }: { config: PayFinalConfig; onSaved: () => void }) {
  const [brackets, setBrackets] = useState<BracketRow[]>(
    config.brackets.map((b) => ({
      component: b.component,
      min_years: String(b.min_years),
      max_years: b.max_years === null ? "" : String(b.max_years),
      months: String(b.months),
    })),
  );
  const [factors, setFactors] = useState<FactorRow[]>(
    config.reason_factors.map((f) => ({
      reason: f.reason,
      pesangon_factor: String(f.pesangon_factor),
      upmk_factor: String(f.upmk_factor),
      uph_included: f.uph_included,
      pkwt_compensation: f.pkwt_compensation,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  function setB(i: number, patch: Partial<BracketRow>) {
    setBrackets((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
  function setF(i: number, patch: Partial<FactorRow>) {
    setFactors((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  async function save() {
    setBusy(true);
    setErr(null);
    setOk(false);
    try {
      const payload = {
        brackets: brackets.map((b) => ({
          component: b.component,
          min_years: Number(b.min_years),
          max_years: b.max_years.trim() === "" ? null : Number(b.max_years),
          months: Number(b.months),
        })),
        reason_factors: factors.map((f) => ({
          reason: f.reason.trim(),
          pesangon_factor: Number(f.pesangon_factor),
          upmk_factor: Number(f.upmk_factor),
          uph_included: f.uph_included,
          pkwt_compensation: f.pkwt_compensation,
        })),
      };
      await apiFetch("/final-pay/config", { method: "PUT", body: JSON.stringify(payload) });
      setOk(true);
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Gagal menyimpan konfigurasi.");
    } finally {
      setBusy(false);
    }
  }

  const cell = "w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none";
  return (
    <div className="space-y-6">
      {err && <ErrorBox message={err} />}
      {ok && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          Konfigurasi tersimpan. Perhitungan baru memakai tabel ini.
        </div>
      )}
      {(["pesangon", "upmk"] as const).map((comp) => (
        <div key={comp}>
          <p className="mb-2 text-sm font-semibold text-slate-800">
            {comp === "pesangon" ? "Bracket uang pesangon" : "Bracket UPMK"} (masa kerja → bulan upah)
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-2 py-1.5">Min (tahun)</th>
                  <th className="px-2 py-1.5">Maks (tahun, kosong = ∞)</th>
                  <th className="px-2 py-1.5">Bulan upah</th>
                  <th className="px-2 py-1.5"></th>
                </tr>
              </thead>
              <tbody>
                {brackets.map((b, i) =>
                  b.component !== comp ? null : (
                    <tr key={i}>
                      <td className="px-2 py-1"><input className={cell} value={b.min_years} onChange={(e) => setB(i, { min_years: e.target.value })} inputMode="decimal" /></td>
                      <td className="px-2 py-1"><input className={cell} value={b.max_years} onChange={(e) => setB(i, { max_years: e.target.value })} inputMode="decimal" /></td>
                      <td className="px-2 py-1"><input className={cell} value={b.months} onChange={(e) => setB(i, { months: e.target.value })} inputMode="numeric" /></td>
                      <td className="px-2 py-1">
                        <button className={`${btnSmall} text-red-600 hover:bg-red-50`} onClick={() => setBrackets((rows) => rows.filter((_, j) => j !== i))}>Hapus</button>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <button
            className={`${btnSmall} mt-2 bg-slate-100 text-slate-700 hover:bg-slate-200`}
            onClick={() => setBrackets((rows) => [...rows, { component: comp, min_years: "", max_years: "", months: "" }])}
          >
            + Baris {comp}
          </button>
        </div>
      ))}

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-800">Faktor per alasan terminasi</p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="px-2 py-1.5">Alasan</th>
                <th className="px-2 py-1.5">Faktor pesangon</th>
                <th className="px-2 py-1.5">Faktor UPMK</th>
                <th className="px-2 py-1.5">UPH sisa cuti</th>
                <th className="px-2 py-1.5">Kompensasi PKWT</th>
                <th className="px-2 py-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {factors.map((f, i) => (
                <tr key={i}>
                  <td className="px-2 py-1"><input className={cell} value={f.reason} onChange={(e) => setF(i, { reason: e.target.value })} /></td>
                  <td className="px-2 py-1"><input className={cell} value={f.pesangon_factor} onChange={(e) => setF(i, { pesangon_factor: e.target.value })} inputMode="decimal" /></td>
                  <td className="px-2 py-1"><input className={cell} value={f.upmk_factor} onChange={(e) => setF(i, { upmk_factor: e.target.value })} inputMode="decimal" /></td>
                  <td className="px-2 py-1 text-center"><input type="checkbox" checked={f.uph_included} onChange={(e) => setF(i, { uph_included: e.target.checked })} /></td>
                  <td className="px-2 py-1 text-center"><input type="checkbox" checked={f.pkwt_compensation} onChange={(e) => setF(i, { pkwt_compensation: e.target.checked })} /></td>
                  <td className="px-2 py-1">
                    <button className={`${btnSmall} text-red-600 hover:bg-red-50`} onClick={() => setFactors((rows) => rows.filter((_, j) => j !== i))}>Hapus</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          className={`${btnSmall} mt-2 bg-slate-100 text-slate-700 hover:bg-slate-200`}
          onClick={() => setFactors((rows) => [...rows, { reason: "", pesangon_factor: "1", upmk_factor: "1", uph_included: true, pkwt_compensation: false }])}
        >
          + Alasan
        </button>
      </div>

      <div className="flex justify-end">
        <button className={btnPrimary} disabled={busy} onClick={() => void save()}>
          {busy ? "Menyimpan…" : "Simpan Konfigurasi"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Halaman utama
// ---------------------------------------------------------------------------
export default function FinalPayPage() {
  const [config, setConfig] = useState<PayFinalConfig | null>(null);
  const [candidates, setCandidates] = useState<PayFinalCandidate[]>([]);
  const [items, setItems] = useState<PayFinal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const [employmentId, setEmploymentId] = useState("");
  const [reason, setReason] = useState("");
  const [termDate, setTermDate] = useState("");
  const [adjustments, setAdjustments] = useState<{ label: string; amount: string }[]>([]);
  const [preview, setPreview] = useState<PayFinalPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const [detail, setDetail] = useState<PayFinal | null>(null);
  const [confirm, setConfirm] = useState<{ kind: string; item: PayFinal } | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [cfg, cands, list] = await Promise.all([
        apiFetch<PayFinalConfig>("/final-pay/config"),
        apiFetch<PayFinalCandidate[]>("/final-pay/candidates"),
        apiFetch<PayFinal[]>("/final-pay"),
      ]);
      setConfig(cfg);
      setCandidates(cands);
      setItems(list);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat data final pay.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function payload() {
    return {
      employment_id: employmentId,
      reason: reason.trim() === "" ? undefined : reason.trim(),
      termination_date: termDate === "" ? undefined : termDate,
      adjustments: adjustments
        .filter((a) => a.label.trim() !== "")
        .map((a) => ({ label: a.label.trim(), amount: Number(a.amount) || 0 })),
    };
  }

  async function doPreview() {
    setBusy(true);
    setActionError(null);
    try {
      setPreview(await apiFetch<PayFinalPreview>("/final-pay/preview", {
        method: "POST",
        body: JSON.stringify(payload()),
      }));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menghitung pratinjau.");
    } finally {
      setBusy(false);
    }
  }

  async function doCreate() {
    setBusy(true);
    setActionError(null);
    try {
      await apiFetch("/final-pay", { method: "POST", body: JSON.stringify(payload()) });
      setSuccessMsg("Draf final pay tersimpan.");
      setPreview(null);
      setAdjustments([]);
      setEmploymentId("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menyimpan final pay.");
    } finally {
      setBusy(false);
    }
  }

  async function doAction(kind: string, item: PayFinal) {
    setBusy(true);
    setActionError(null);
    try {
      if (kind === "delete") {
        await apiFetch(`/final-pay/${item.id}`, { method: "DELETE" });
        setSuccessMsg("Draf final pay dihapus.");
      } else {
        await apiFetch(`/final-pay/${item.id}/${kind}`, { method: "POST" });
        setSuccessMsg(kind === "finalize" ? "Final pay difinalisasi." : "Final pay ditandai dibayar.");
      }
      setConfirm(null);
      setDetail(null);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Aksi gagal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Final Pay & Pesangon"
        subtitle="Pembayaran akhir karyawan yang berakhir masa kerjanya: sisa gaji, sisa cuti, pesangon/UPMK/UPH per alasan terminasi dengan tabel yang dapat dikonfigurasi (bawaan mengikuti PP 35/2021)."
      />

      {error && <div className="mb-4"><ErrorBox message={error} onRetry={() => void load()} /></div>}
      {actionError && <div className="mb-4"><ErrorBox message={actionError} /></div>}
      {successMsg && (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {successMsg}
        </div>
      )}

      {loading ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          <Card title="Buat final pay" subtitle="Pilih karyawan yang sudah berstatus terminated; alasan & tanggal diambil dari kejadian terminasi, dapat ditimpa bila perlu.">
            {candidates.length === 0 ? (
              <EmptyState message="Belum ada karyawan berstatus terminated di tenant ini." />
            ) : (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="Karyawan (terminated)" required>
                    <select
                      className={inputCls}
                      value={employmentId}
                      onChange={(e) => { setEmploymentId(e.target.value); setPreview(null); }}
                    >
                      <option value="">— pilih —</option>
                      {candidates.map((c) => (
                        <option key={c.employment_id} value={c.employment_id} disabled={c.has_final_pay}>
                          {c.person_name}
                          {c.termination_date ? ` · ${tanggal(c.termination_date)}` : ""}
                          {c.reason ? ` · ${c.reason}` : ""}
                          {c.has_final_pay ? " · (sudah ada final pay)" : ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Alasan (timpa bila perlu)">
                    <input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. PHK" />
                  </Field>
                  <Field label="Tanggal terminasi (timpa bila perlu)">
                    <input type="date" className={inputCls} value={termDate} onChange={(e) => setTermDate(e.target.value)} />
                  </Field>
                </div>

                <div>
                  <p className="mb-2 text-sm font-medium text-slate-700">Penyesuaian manual (mis. uang pisah, biaya pulang)</p>
                  <div className="space-y-2">
                    {adjustments.map((a, i) => (
                      <div key={i} className="flex gap-2">
                        <input
                          className={inputCls}
                          placeholder="Label"
                          value={a.label}
                          onChange={(e) => setAdjustments((rows) => rows.map((r, j) => (j === i ? { ...r, label: e.target.value } : r)))}
                        />
                        <input
                          className={inputCls}
                          placeholder="Nominal (boleh negatif)"
                          value={a.amount}
                          inputMode="numeric"
                          onChange={(e) => setAdjustments((rows) => rows.map((r, j) => (j === i ? { ...r, amount: e.target.value } : r)))}
                        />
                        <button className={`${btnSmall} shrink-0 text-red-600 hover:bg-red-50`} onClick={() => setAdjustments((rows) => rows.filter((_, j) => j !== i))}>
                          Hapus
                        </button>
                      </div>
                    ))}
                  </div>
                  <button className={`${btnSmall} mt-2 bg-slate-100 text-slate-700 hover:bg-slate-200`} onClick={() => setAdjustments((rows) => [...rows, { label: "", amount: "" }])}>
                    + Penyesuaian
                  </button>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button className={btnSecondary} disabled={busy || employmentId === ""} onClick={() => void doPreview()}>
                    {busy ? "Menghitung…" : "Pratinjau hitungan"}
                  </button>
                  <button className={btnPrimary} disabled={busy || preview === null} onClick={() => void doCreate()}>
                    Simpan sebagai draf
                  </button>
                </div>

                {preview && (
                  <div>
                    <p className="mb-2 text-sm text-slate-600">
                      Pratinjau untuk <strong>{preview.person_name}</strong> · alasan {preview.reason} · terminasi {tanggal(preview.termination_date)}
                    </p>
                    <BreakdownRows fp={preview} />
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card title="Daftar final pay" subtitle="Draf dapat dihapus & dihitung ulang; angka terkunci setelah finalisasi.">
            {items.length === 0 ? (
              <EmptyState message="Belum ada final pay. Buat dari formulir di atas." />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-slate-100 text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                      <th className="px-3 py-2">Karyawan</th>
                      <th className="px-3 py-2">Terminasi</th>
                      <th className="px-3 py-2">Alasan</th>
                      <th className="px-3 py-2 text-right">Masa kerja (th)</th>
                      <th className="px-3 py-2 text-right">Neto</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {items.map((it) => (
                      <tr key={it.id} className="hover:bg-slate-50">
                        <td className="px-3 py-2.5 font-medium text-slate-800">{it.person_name ?? "-"}</td>
                        <td className="px-3 py-2.5 text-slate-600">{tanggal(it.termination_date)}</td>
                        <td className="px-3 py-2.5 text-slate-600">{it.reason}</td>
                        <td className="px-3 py-2.5 text-right text-slate-600">{it.years_of_service.toLocaleString("id-ID")}</td>
                        <td className="px-3 py-2.5 text-right font-medium text-slate-900">{rupiah(it.net_amount)}</td>
                        <td className="px-3 py-2.5"><StatusPill status={it.status} /></td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-wrap gap-1.5">
                            <button className={`${btnSmall} bg-slate-100 text-slate-700 hover:bg-slate-200`} onClick={() => setDetail(it)}>Detail</button>
                            {it.status === "draft" && (
                              <>
                                <button className={`${btnSmall} bg-brand-600 text-white hover:bg-brand-700`} onClick={() => setConfirm({ kind: "finalize", item: it })}>Finalisasi</button>
                                <button className={`${btnSmall} bg-red-50 text-red-700 hover:bg-red-100`} onClick={() => setConfirm({ kind: "delete", item: it })}>Hapus</button>
                              </>
                            )}
                            {it.status === "finalized" && (
                              <button className={`${btnSmall} bg-emerald-600 text-white hover:bg-emerald-700`} onClick={() => setConfirm({ kind: "pay", item: it })}>Tandai dibayar</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {config && (
            <Card title="Konfigurasi tabel pesangon" subtitle="Bracket masa kerja & faktor per alasan per tenant — ganti di sini saat aturan ketenagakerjaan atau kebijakan perusahaan berubah.">
              <ConfigEditor config={config} onSaved={() => void load()} />
            </Card>
          )}
        </div>
      )}

      {detail && (
        <Modal title={`Final pay — ${detail.person_name ?? ""}`} onClose={() => setDetail(null)} actions={
          <button className={btnSecondary} onClick={() => setDetail(null)}>Tutup</button>
        }>
          <p className="mb-3 text-sm text-slate-600">
            Alasan {detail.reason} · terminasi {tanggal(detail.termination_date)} · status {STATUS_LABEL[detail.status]?.label ?? detail.status}
            {detail.notes ? ` · Catatan: ${detail.notes}` : ""}
          </p>
          <BreakdownRows fp={detail} />
        </Modal>
      )}

      {confirm && (
        <Modal
          title={
            confirm.kind === "finalize" ? "Finalisasi final pay?" :
            confirm.kind === "pay" ? "Tandai sudah dibayar?" : "Hapus draf final pay?"
          }
          onClose={() => setConfirm(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setConfirm(null)}>Batal</button>
              <button
                className={confirm.kind === "delete" ? btnDanger : btnPrimary}
                disabled={busy}
                onClick={() => void doAction(confirm.kind, confirm.item)}
              >
                {busy ? "Memproses…" : "Ya, lanjutkan"}
              </button>
            </>
          }
        >
          {confirm.kind === "finalize" && "Angka final pay akan terkunci dan tidak dapat diubah lagi. Lanjutkan?"}
          {confirm.kind === "pay" && "Final pay ditandai sudah dibayarkan ke karyawan. Lanjutkan?"}
          {confirm.kind === "delete" && "Draf akan dihapus permanen; Anda dapat menghitung ulang setelahnya. Lanjutkan?"}
        </Modal>
      )}
    </div>
  );
}
