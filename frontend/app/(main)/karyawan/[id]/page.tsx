"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError, apiDownload } from "@/lib/api";
import type { Person, Employment, JobInfo, Contract, Document } from "@/lib/types";
import { tanggal, angka } from "@/lib/format";
import {
  PageHeader,
  Card,
  Spinner,
  ErrorBox,
  EmptyState,
  inputCls,
  btnSmall,
} from "@/components/ui";

function Dl({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="py-2">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{value}</dd>
    </div>
  );
}

function genderLabel(g: string | null): string {
  if (g === "L") return "Laki-laki";
  if (g === "P") return "Perempuan";
  return "-";
}

function statusEmployment(s: string): string {
  const map: Record<string, string> = {
    active: "Aktif",
    inactive: "Tidak aktif",
    terminated: "Berakhir",
    probation: "Masa percobaan",
  };
  return map[s] ?? s;
}

export default function KaryawanDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [person, setPerson] = useState<Person | null>(null);
  const [employments, setEmployments] = useState<Employment[]>([]);
  const [empId, setEmpId] = useState<string>("");
  const [timeline, setTimeline] = useState<JobInfo[] | null>(null);
  const [contracts, setContracts] = useState<Contract[] | null>(null);
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [tabLoading, setTabLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tabError, setTabError] = useState<string | null>(null);
  const [dlBusy, setDlBusy] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [p, emps] = await Promise.all([
          apiFetch<Person>(`/persons/${id}`),
          apiFetch<Employment[]>("/employments"),
        ]);
        const mine = emps.filter((e) => e.person_id === id);
        setPerson(p);
        setEmployments(mine);
        if (mine.length > 0) setEmpId(mine[0].id);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Gagal memuat data karyawan.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  useEffect(() => {
    if (!empId) return;
    async function loadTabs() {
      setTabLoading(true);
      setTabError(null);
      try {
        const [tl, ct, dc] = await Promise.all([
          apiFetch<JobInfo[]>(`/job-info/timeline?employment_id=${empId}`),
          apiFetch<Contract[]>(`/contracts?employment_id=${empId}`),
          apiFetch<Document[]>(`/documents?person_id=${id}`),
        ]);
        setTimeline(tl);
        setContracts(ct);
        setDocuments(dc);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          // Sebagian tab boleh kosong (mis. belum ada job info).
          setTimeline([]);
          setContracts([]);
          setDocuments([]);
        } else {
          setTabError(err instanceof ApiError ? err.message : "Gagal memuat data tambahan.");
        }
      } finally {
        setTabLoading(false);
      }
    }
    loadTabs();
  }, [empId, id]);

  async function downloadDoc(doc: Document) {
    setDlBusy(doc.id);
    try {
      await apiDownload(`/documents/${doc.id}/download`, doc.file_name);
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Gagal mengunduh dokumen.");
    } finally {
      setDlBusy(null);
    }
  }

  if (loading) return <Spinner label="Memuat detail karyawan…" />;
  if (error || !person)
    return <ErrorBox message={error ?? "Data tidak ditemukan."} />;

  return (
    <div>
      <PageHeader
        title={person.full_name}
        subtitle={`NIK ${person.nik}`}
        action={
          <Link href="/karyawan" className="text-sm font-medium text-brand-600 hover:text-brand-700">
            ← Kembali ke daftar
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Data pribadi">
          <dl className="grid grid-cols-2 gap-x-6 divide-y divide-slate-100">
            <Dl label="Nama lengkap" value={person.full_name} />
            <Dl label="NIK" value={<span className="font-mono">{person.nik}</span>} />
            <Dl label="Tempat, tgl. lahir" value={`${person.birth_place ?? "-"}, ${tanggal(person.birth_date)}`} />
            <Dl label="Jenis kelamin" value={genderLabel(person.gender)} />
            <Dl label="Email" value={person.email ?? "-"} />
            <Dl label="Telepon" value={person.phone ?? "-"} />
            <Dl label="NPWP" value={person.npwp ?? "-"} />
            <Dl label="PTKP" value={person.ptkp} />
            <Dl label="BPJS Kesehatan" value={person.bpjs_kes_no ?? "-"} />
            <Dl label="BPJS Ketenagakerjaan" value={person.bpjs_tk_no ?? "-"} />
            <Dl label="Bank" value={person.bank_name ?? "-"} />
            <Dl label="No. rekening" value={<span className="font-mono">{person.bank_account_no ?? "-"}</span>} />
          </dl>
        </Card>

        <Card title="Riwayat kepegawaian">
          {employments.length === 0 ? (
            <EmptyState message="Belum ada data employment." />
          ) : (
            <>
              {employments.length > 1 && (
                <div className="mb-4">
                  <select
                    className={inputCls}
                    value={empId}
                    onChange={(e) => setEmpId(e.target.value)}
                  >
                    {employments.map((e, i) => (
                      <option key={e.id} value={e.id}>
                        Employment {i + 1} — mulai {tanggal(e.start_date)}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {employments
                .filter((e) => e.id === empId)
                .map((e) => (
                  <dl key={e.id} className="divide-y divide-slate-100">
                    <Dl label="Status" value={statusEmployment(e.status)} />
                    <Dl label="Tanggal mulai" value={tanggal(e.start_date)} />
                    <Dl label="Tanggal berakhir" value={tanggal(e.end_date)} />
                  </dl>
                ))}
            </>
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Timeline jabatan">
          {tabLoading && <Spinner label="Memuat…" />}
          {tabError && <ErrorBox message={tabError} />}
          {!tabLoading && !tabError && (
            timeline && timeline.length > 0 ? (
              <ol className="space-y-3">
                {timeline.map((j) => (
                  <li key={j.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                    <p className="font-medium text-slate-900">{j.event}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {tanggal(j.valid_from)} s.d. {tanggal(j.valid_to)}
                    </p>
                    {j.event_reason && (
                      <p className="mt-1 text-xs text-slate-600">{j.event_reason}</p>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState message="Belum ada riwayat jabatan." />
            )
          )}
        </Card>

        <Card title="Kontrak">
          {tabLoading && <Spinner label="Memuat…" />}
          {tabError && <ErrorBox message={tabError} />}
          {!tabLoading && !tabError && (
            contracts && contracts.length > 0 ? (
              <div className="space-y-3">
                {contracts.flatMap((c) => c.versions).map((v) => (
                  <div key={v.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                    <p className="font-medium text-slate-900">{v.contract_type}</p>
                    <p className="text-xs text-slate-500">No. {v.contract_number}</p>
                    <p className="mt-1 text-xs text-slate-600">
                      {tanggal(v.valid_from)} s.d. {tanggal(v.valid_to)}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState message="Belum ada data kontrak." />
            )
          )}
        </Card>

        <Card title="Dokumen">
          {tabLoading && <Spinner label="Memuat…" />}
          {tabError && <ErrorBox message={tabError} />}
          {!tabLoading && !tabError && (
            documents && documents.length > 0 ? (
              <ul className="space-y-2">
                {documents.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 p-3 text-sm"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900">{d.file_name}</p>
                      <p className="text-xs text-slate-500">
                        {d.doc_type} · {angka(Math.round(d.size_bytes / 1024))} KB
                      </p>
                    </div>
                    <button
                      onClick={() => downloadDoc(d)}
                      disabled={dlBusy === d.id}
                      className={`${btnSmall} shrink-0 bg-brand-600 text-white hover:bg-brand-700`}
                    >
                      {dlBusy === d.id ? "…" : "Unduh"}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState message="Belum ada dokumen." />
            )
          )}
        </Card>
      </div>
    </div>
  );
}
