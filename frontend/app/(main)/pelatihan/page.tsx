"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { EmptyState, Modal } from "@/components/ui";
import { rupiah } from "@/lib/format";

interface Course {
  id: string;
  code: string;
  name: string;
  provider: string | null;
  duration_hours: number;
  cost: number;
  content_type: string;
  content_url: string | null;
  passing_score: number | null;
  cert_validity_months: number | null;
}

interface Enrollment {
  id: string;
  employment_id: string;
  course_id: string;
  cycle_id: string | null;
  status: string;
  completed_at: string | null;
  certificate_document_id: string | null;
  progress_percent: number;
  due_date: string | null;
  is_mandatory: boolean;
  pre_score: number | null;
  post_score: number | null;
  cert_expires_at: string | null;
  is_overdue: boolean;
}

interface Assignment {
  id: string;
  course_id: string;
  target_type: string;
  org_unit_id: string | null;
  job_id: string | null;
  due_days: number;
  enrollments_created: number;
  created_at: string;
}

interface ExpiringCert {
  enrollment_id: string;
  employment_id: string;
  person_name: string;
  course_code: string;
  course_name: string;
  cert_expires_at: string;
  days_remaining: number;
}

interface Employment {
  id: string;
  person_id: string;
  status: string;
}

interface Person {
  id: string;
  full_name: string;
}

interface OrgJob {
  id: string;
  code: string;
  title: string;
}

interface OrgUnit {
  id: string;
  name: string;
}

const ENROLL_STATUS_LABEL: Record<string, string> = {
  registered: "Terdaftar",
  in_progress: "Berjalan",
  completed: "Selesai",
  cancelled: "Dibatalkan",
};

const CONTENT_LABEL: Record<string, string> = {
  pdf: "PDF",
  video: "Video",
  link: "Tautan",
  offline: "Luring/Kelas",
};

export default function PelatihanPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [overdue, setOverdue] = useState<Enrollment[]>([]);
  const [expiring, setExpiring] = useState<ExpiringCert[]>([]);
  const [jobs, setJobs] = useState<OrgJob[]>([]);
  const [units, setUnits] = useState<OrgUnit[]>([]);
  const [employments, setEmployments] = useState<Employment[]>([]);
  const [personMap, setPersonMap] = useState<Map<string, string>>(new Map());
  const [courseMap, setCourseMap] = useState<Map<string, Course>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [showCourseForm, setShowCourseForm] = useState(false);
  const [cCode, setCCode] = useState("");
  const [cName, setCName] = useState("");
  const [cProvider, setCProvider] = useState("");
  const [cHours, setCHours] = useState(8);
  const [cCost, setCCost] = useState(0);
  const [cContentType, setCContentType] = useState("offline");
  const [cContentUrl, setCContentUrl] = useState("");
  const [cPassing, setCPassing] = useState("");
  const [cValidity, setCValidity] = useState("");

  const [showEnrollForm, setShowEnrollForm] = useState(false);
  const [eEmp, setEEmp] = useState("");
  const [eCourse, setECourse] = useState("");

  const [progEnr, setProgEnr] = useState<Enrollment | null>(null);
  const [pPct, setPPct] = useState(0);
  const [pPre, setPPre] = useState("");
  const [pPost, setPPost] = useState("");

  const [aCourse, setACourse] = useState("");
  const [aTarget, setATarget] = useState("all");
  const [aUnit, setAUnit] = useState("");
  const [aJob, setAJob] = useState("");
  const [aDays, setADays] = useState(30);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cs, en, emps, persons] = await Promise.all([
        apiFetch<Course[]>("/performance/courses"),
        apiFetch<Enrollment[]>("/performance/enrollments"),
        apiFetch<Employment[]>("/employments"),
        apiFetch<Person[]>("/persons"),
      ]);
      setCourses(cs);
      setCourseMap(new Map(cs.map((c) => [c.id, c])));
      setEnrollments(en);
      const pm = new Map(persons.map((p) => [p.id, p.full_name]));
      const active = emps.filter(
        (e) => e.status === "active" && pm.has(e.person_id)
      );
      setEmployments(active);
      setPersonMap(pm);
      if (active.length > 0) setEEmp((prev) => prev || active[0].id);
      if (cs.length > 0) {
        setECourse((prev) => prev || cs[0].id);
        setACourse((prev) => prev || cs[0].id);
      }
      // Data pendukung (boleh gagal diam-diam bila peran tak berizin).
      const [asg, ov, ex, jb, un] = await Promise.all([
        apiFetch<Assignment[]>("/performance/assignments").catch(() => []),
        apiFetch<Enrollment[]>("/performance/learning/overdue").catch(
          () => []
        ),
        apiFetch<ExpiringCert[]>(
          "/performance/learning/certifications/expiring?within_days=90"
        ).catch(() => []),
        apiFetch<OrgJob[]>("/org/jobs").catch(() => []),
        apiFetch<OrgUnit[]>("/org/units").catch(() => []),
      ]);
      setAssignments(asg);
      setOverdue(ov);
      setExpiring(ex);
      setJobs(jb);
      setUnits(un);
      if (jb.length > 0) setAJob((prev) => prev || jb[0].id);
      if (un.length > 0) setAUnit((prev) => prev || un[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createCourse(e: React.FormEvent) {
    e.preventDefault();
    if (!cCode.trim() || !cName.trim()) {
      setMsg("Kode dan nama kursus wajib diisi.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch("/performance/courses", {
        method: "POST",
        body: JSON.stringify({
          code: cCode.trim(),
          name: cName.trim(),
          provider: cProvider.trim() || null,
          duration_hours: cHours,
          cost: cCost,
          content_type: cContentType,
          content_url: cContentUrl.trim() || null,
          passing_score: cPassing === "" ? null : Number(cPassing),
          cert_validity_months: cValidity === "" ? null : Number(cValidity),
        }),
      });
      setShowCourseForm(false);
      setCCode("");
      setCName("");
      setCProvider("");
      setCHours(8);
      setCCost(0);
      setCContentType("offline");
      setCContentUrl("");
      setCPassing("");
      setCValidity("");
      setMsg("Kursus berhasil ditambahkan.");
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal menambah kursus.");
    } finally {
      setBusy(false);
    }
  }

  async function enroll(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch("/performance/enrollments", {
        method: "POST",
        body: JSON.stringify({ employment_id: eEmp, course_id: eCourse }),
      });
      setShowEnrollForm(false);
      setMsg("Pendaftaran berhasil.");
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal mendaftar.");
    } finally {
      setBusy(false);
    }
  }

  async function saveProgress(e: React.FormEvent) {
    e.preventDefault();
    if (!progEnr) return;
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/performance/enrollments/${progEnr.id}/progress`, {
        method: "POST",
        body: JSON.stringify({
          progress_percent: pPct,
          pre_score: pPre === "" ? null : Number(pPre),
          post_score: pPost === "" ? null : Number(pPost),
        }),
      });
      setProgEnr(null);
      setMsg("Progres belajar tersimpan.");
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal menyimpan progres.");
    } finally {
      setBusy(false);
    }
  }

  async function completeEnrollment(id: string) {
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/performance/enrollments/${id}/complete`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setMsg("Pelatihan ditandai selesai. Sertifikat diterbitkan otomatis.");
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal menyelesaikan.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelEnrollment(id: string) {
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/performance/enrollments/${id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: "Dibatalkan via UI" }),
      });
      setMsg("Pendaftaran dibatalkan.");
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal membatalkan.");
    } finally {
      setBusy(false);
    }
  }

  async function createAssignment(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const res = await apiFetch<Assignment>("/performance/assignments", {
        method: "POST",
        body: JSON.stringify({
          course_id: aCourse,
          target_type: aTarget,
          org_unit_id: aTarget === "org_unit" ? aUnit : null,
          job_id: aTarget === "job" ? aJob : null,
          due_days: aDays,
        }),
      });
      setMsg(
        `Penugasan dibuat: ${res.enrollments_created} pendaftaran wajib baru (tenggat ${aDays} hari).`
      );
      await load();
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : "Gagal membuat penugasan.");
    } finally {
      setBusy(false);
    }
  }

  const empName = (id: string) => {
    const e = employments.find((x) => x.id === id);
    return e ? (personMap.get(e.person_id) ?? id.slice(0, 8)) : id.slice(0, 8);
  };

  const inputCls =
    "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  const labelCls = "mb-1 block text-xs font-medium text-slate-700";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Pelatihan</h1>
        <p className="mt-1 text-sm text-slate-500">
          Katalog kursus, pendaftaran, progres belajar, penugasan wajib, dan
          sertifikasi. Rekomendasi kursus per karyawan tersedia di tab
          “Rekomendasi Pelatihan” pada detail siklus.
        </p>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
      {msg && (
        <div className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800">
          {msg}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Katalog kursus</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setShowEnrollForm(true)}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Daftarkan karyawan
          </button>
          <button
            onClick={() => setShowCourseForm(true)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + Kursus baru
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Memuat…</p>
      ) : courses.length === 0 ? (
        <EmptyState message="Belum ada kursus di katalog." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {courses.map((c) => (
            <div key={c.id} className="rounded-xl bg-white p-4 shadow">
              <p className="text-xs font-mono text-slate-400">{c.code}</p>
              <p className="mt-0.5 font-medium text-slate-900">{c.name}</p>
              <p className="mt-1 text-xs text-slate-500">
                {c.provider ?? "—"} · {c.duration_hours} jam ·{" "}
                {c.cost > 0 ? rupiah(c.cost) : "Gratis"}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Konten: {CONTENT_LABEL[c.content_type] ?? c.content_type}
                {c.content_url ? (
                  <>
                    {" · "}
                    <a
                      href={c.content_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 underline"
                    >
                      Buka materi
                    </a>
                  </>
                ) : null}
              </p>
              {(c.passing_score !== null || c.cert_validity_months !== null) && (
                <p className="mt-1 text-xs text-slate-500">
                  {c.passing_score !== null
                    ? `Nilai lulus ${c.passing_score}`
                    : ""}
                  {c.passing_score !== null && c.cert_validity_months !== null
                    ? " · "
                    : ""}
                  {c.cert_validity_months !== null
                    ? `Sertifikat berlaku ${c.cert_validity_months} bulan`
                    : ""}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <h2 className="text-lg font-semibold text-slate-900">Pendaftaran</h2>
      {enrollments.length === 0 ? (
        <EmptyState message="Belum ada pendaftaran pelatihan." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Karyawan</th>
                <th className="px-4 py-3">Kursus</th>
                <th className="px-4 py-3">Progres</th>
                <th className="px-4 py-3">Nilai Pre/Post</th>
                <th className="px-4 py-3">Tenggat</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {enrollments.map((en) => (
                <tr key={en.id} className="border-b last:border-0">
                  <td className="px-4 py-3">{empName(en.employment_id)}</td>
                  <td className="px-4 py-3">
                    {courseMap.get(en.course_id)?.name ?? en.course_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="h-2 w-24 rounded-full bg-slate-100">
                      <div
                        className="h-2 rounded-full bg-blue-600"
                        style={{ width: `${en.progress_percent}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-500">
                      {en.progress_percent}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {en.pre_score ?? "—"} / {en.post_score ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {en.due_date ?? "—"}
                    {en.is_mandatory && (
                      <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
                        Wajib
                      </span>
                    )}
                    {en.is_overdue && (
                      <span className="ml-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-700">
                        Terlambat
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                      {ENROLL_STATUS_LABEL[en.status] ?? en.status}
                    </span>
                    {en.status === "completed" && en.cert_expires_at && (
                      <p className="mt-1 text-[11px] text-slate-500">
                        Sertifikat s.d. {en.cert_expires_at}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {en.status !== "completed" && en.status !== "cancelled" && (
                        <>
                          <button
                            onClick={() => {
                              setProgEnr(en);
                              setPPct(en.progress_percent);
                              setPPre(
                                en.pre_score === null ? "" : String(en.pre_score)
                              );
                              setPPost(
                                en.post_score === null
                                  ? ""
                                  : String(en.post_score)
                              );
                            }}
                            disabled={busy}
                            className="rounded-lg border border-blue-600 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                          >
                            Progres
                          </button>
                          <button
                            onClick={() => completeEnrollment(en.id)}
                            disabled={busy}
                            className="rounded-lg border border-emerald-600 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                          >
                            Selesaikan
                          </button>
                          <button
                            onClick={() => cancelEnrollment(en.id)}
                            disabled={busy}
                            className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                          >
                            Batalkan
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="text-lg font-semibold text-slate-900">Penugasan wajib</h2>
      <form
        onSubmit={createAssignment}
        className="grid gap-3 rounded-xl bg-white p-4 shadow sm:grid-cols-2 lg:grid-cols-5"
      >
        <div>
          <label className={labelCls}>Kursus</label>
          <select
            value={aCourse}
            onChange={(e) => setACourse(e.target.value)}
            className={inputCls}
          >
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>Target penugasan</label>
          <select
            value={aTarget}
            onChange={(e) => setATarget(e.target.value)}
            className={inputCls}
          >
            <option value="all">Semua karyawan</option>
            <option value="org_unit">Unit organisasi</option>
            <option value="job">Jabatan</option>
          </select>
        </div>
        {aTarget === "org_unit" && (
          <div>
            <label className={labelCls}>Unit organisasi</label>
            <select
              value={aUnit}
              onChange={(e) => setAUnit(e.target.value)}
              className={inputCls}
            >
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {aTarget === "job" && (
          <div>
            <label className={labelCls}>Jabatan</label>
            <select
              value={aJob}
              onChange={(e) => setAJob(e.target.value)}
              className={inputCls}
            >
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.code} — {j.title}
                </option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className={labelCls}>Tenggat (hari)</label>
          <input
            type="number"
            min={1}
            max={365}
            value={aDays}
            onChange={(e) => setADays(Number(e.target.value))}
            className={inputCls}
          />
        </div>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={busy || courses.length === 0}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Tugaskan
          </button>
        </div>
      </form>
      {assignments.length > 0 && (
        <div className="overflow-x-auto rounded-xl bg-white shadow">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Kursus</th>
                <th className="px-4 py-3">Target</th>
                <th className="px-4 py-3">Tenggat</th>
                <th className="px-4 py-3">Pendaftaran dibuat</th>
                <th className="px-4 py-3">Dibuat</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.id} className="border-b last:border-0">
                  <td className="px-4 py-3">
                    {courseMap.get(a.course_id)?.name ?? a.course_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3">
                    {a.target_type === "all"
                      ? "Semua karyawan"
                      : a.target_type === "org_unit"
                        ? (units.find((u) => u.id === a.org_unit_id)?.name ??
                          "Unit")
                        : (jobs.find((j) => j.id === a.job_id)?.title ??
                          "Jabatan")}
                  </td>
                  <td className="px-4 py-3">{a.due_days} hari</td>
                  <td className="px-4 py-3">{a.enrollments_created}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {a.created_at.slice(0, 10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="text-lg font-semibold text-slate-900">
        Pelatihan terlambat
      </h2>
      {overdue.length === 0 ? (
        <EmptyState message="Tidak ada pelatihan yang melewati tenggat." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Karyawan</th>
                <th className="px-4 py-3">Kursus</th>
                <th className="px-4 py-3">Tenggat</th>
                <th className="px-4 py-3">Progres</th>
              </tr>
            </thead>
            <tbody>
              {overdue.map((en) => (
                <tr key={en.id} className="border-b last:border-0">
                  <td className="px-4 py-3">{empName(en.employment_id)}</td>
                  <td className="px-4 py-3">
                    {courseMap.get(en.course_id)?.name ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-red-700">{en.due_date}</td>
                  <td className="px-4 py-3">{en.progress_percent}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="text-lg font-semibold text-slate-900">
        Sertifikasi mendekati kedaluwarsa (90 hari)
      </h2>
      {expiring.length === 0 ? (
        <EmptyState message="Tidak ada sertifikasi yang mendekati kedaluwarsa." />
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b bg-slate-50 text-left text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Karyawan</th>
                <th className="px-4 py-3">Kursus</th>
                <th className="px-4 py-3">Berlaku hingga</th>
                <th className="px-4 py-3">Sisa hari</th>
              </tr>
            </thead>
            <tbody>
              {expiring.map((x) => (
                <tr key={x.enrollment_id} className="border-b last:border-0">
                  <td className="px-4 py-3">{x.person_name}</td>
                  <td className="px-4 py-3">
                    {x.course_code} — {x.course_name}
                  </td>
                  <td className="px-4 py-3">{x.cert_expires_at}</td>
                  <td className="px-4 py-3">
                    {x.days_remaining < 0
                      ? `Kedaluwarsa ${-x.days_remaining} hari lalu`
                      : `${x.days_remaining} hari`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCourseForm && (
        <Modal
          title="Tambah kursus"
          onClose={() => !busy && setShowCourseForm(false)}
          actions={
            <>
              <button
                onClick={() => setShowCourseForm(false)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={createCourse}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Simpan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Kode</label>
              <input
                value={cCode}
                onChange={(e) => setCCode(e.target.value)}
                className={inputCls}
                placeholder="cth. LEAD-101"
              />
            </div>
            <div>
              <label className={labelCls}>Nama kursus</label>
              <input
                value={cName}
                onChange={(e) => setCName(e.target.value)}
                className={inputCls}
                placeholder="cth. Dasar Kepemimpinan"
              />
            </div>
            <div>
              <label className={labelCls}>Penyelenggara</label>
              <input
                value={cProvider}
                onChange={(e) => setCProvider(e.target.value)}
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Durasi (jam)</label>
                <input
                  type="number"
                  min={0}
                  value={cHours}
                  onChange={(e) => setCHours(Number(e.target.value))}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>Biaya (Rp)</label>
                <input
                  type="number"
                  min={0}
                  value={cCost}
                  onChange={(e) => setCCost(Number(e.target.value))}
                  className={inputCls}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Jenis konten</label>
                <select
                  value={cContentType}
                  onChange={(e) => setCContentType(e.target.value)}
                  className={inputCls}
                >
                  <option value="offline">Luring/Kelas</option>
                  <option value="pdf">PDF</option>
                  <option value="video">Video</option>
                  <option value="link">Tautan</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>URL materi (opsional)</label>
                <input
                  value={cContentUrl}
                  onChange={(e) => setCContentUrl(e.target.value)}
                  className={inputCls}
                  placeholder="https://…"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Nilai lulus post-test (opsional)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={cPassing}
                  onChange={(e) => setCPassing(e.target.value)}
                  className={inputCls}
                  placeholder="cth. 70"
                />
              </div>
              <div>
                <label className={labelCls}>
                  Masa berlaku sertifikat, bulan (opsional)
                </label>
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={cValidity}
                  onChange={(e) => setCValidity(e.target.value)}
                  className={inputCls}
                  placeholder="cth. 24 (K3)"
                />
              </div>
            </div>
          </div>
        </Modal>
      )}

      {progEnr && (
        <Modal
          title="Perbarui progres belajar"
          onClose={() => !busy && setProgEnr(null)}
          actions={
            <>
              <button
                onClick={() => setProgEnr(null)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={saveProgress}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Simpan progres"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              {empName(progEnr.employment_id)} —{" "}
              {courseMap.get(progEnr.course_id)?.name ?? ""}
            </p>
            <div>
              <label className={labelCls}>Progres (%)</label>
              <input
                type="number"
                min={0}
                max={100}
                value={pPct}
                onChange={(e) => setPPct(Number(e.target.value))}
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Nilai pre-test (opsional)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={pPre}
                  onChange={(e) => setPPre(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>Nilai post-test (opsional)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={pPost}
                  onChange={(e) => setPPost(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
          </div>
        </Modal>
      )}

      {showEnrollForm && (
        <Modal
          title="Daftarkan karyawan"
          onClose={() => !busy && setShowEnrollForm(false)}
          actions={
            <>
              <button
                onClick={() => setShowEnrollForm(false)}
                disabled={busy}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Batal
              </button>
              <button
                onClick={enroll}
                disabled={busy}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {busy ? "Menyimpan…" : "Daftarkan"}
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Karyawan</label>
              <select
                value={eEmp}
                onChange={(e) => setEEmp(e.target.value)}
                className={inputCls}
              >
                {employments.map((e) => (
                  <option key={e.id} value={e.id}>
                    {personMap.get(e.person_id) ?? "—"}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>Kursus</label>
              <select
                value={eCourse}
                onChange={(e) => setECourse(e.target.value)}
                className={inputCls}
              >
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} — {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
