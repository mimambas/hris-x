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
}

interface Enrollment {
  id: string;
  employment_id: string;
  course_id: string;
  cycle_id: string | null;
  status: string;
  completed_at: string | null;
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

const ENROLL_STATUS_LABEL: Record<string, string> = {
  registered: "Terdaftar",
  in_progress: "Berjalan",
  completed: "Selesai",
  cancelled: "Dibatalkan",
};

export default function PelatihanPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
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

  const [showEnrollForm, setShowEnrollForm] = useState(false);
  const [eEmp, setEEmp] = useState("");
  const [eCourse, setECourse] = useState("");

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
      // Hanya employment yang orangnya terlihat oleh user (hindari label ID
      // mentah + pilihan yang berujung "akses ditolak").
      const active = emps.filter(
        (e) => e.status === "active" && pm.has(e.person_id)
      );
      setEmployments(active);
      setPersonMap(pm);
      if (active.length > 0) setEEmp((prev) => prev || active[0].id);
      if (cs.length > 0) setECourse((prev) => prev || cs[0].id);
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
        }),
      });
      setShowCourseForm(false);
      setCCode("");
      setCName("");
      setCProvider("");
      setCHours(8);
      setCCost(0);
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

  async function completeEnrollment(id: string) {
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/performance/enrollments/${id}/complete`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setMsg("Pelatihan ditandai selesai.");
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

  const empName = (id: string) => {
    const e = employments.find((x) => x.id === id);
    return e ? (personMap.get(e.person_id) ?? id.slice(0, 8)) : id.slice(0, 8);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Pelatihan</h1>
        <p className="mt-1 text-sm text-slate-500">
          Katalog kursus dan pendaftaran karyawan. Rekomendasi kursus per
          karyawan tersedia di tab “Rekomendasi Pelatihan” pada detail siklus.
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
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                      {ENROLL_STATUS_LABEL[en.status] ?? en.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {en.status !== "completed" && en.status !== "cancelled" && (
                        <>
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
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Kode
              </label>
              <input
                value={cCode}
                onChange={(e) => setCCode(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="cth. LEAD-101"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Nama kursus
              </label>
              <input
                value={cName}
                onChange={(e) => setCName(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="cth. Dasar Kepemimpinan"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Penyelenggara
              </label>
              <input
                value={cProvider}
                onChange={(e) => setCProvider(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-700">
                  Durasi (jam)
                </label>
                <input
                  type="number"
                  min={0}
                  value={cHours}
                  onChange={(e) => setCHours(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-700">
                  Biaya (Rp)
                </label>
                <input
                  type="number"
                  min={0}
                  value={cCost}
                  onChange={(e) => setCCost(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
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
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Karyawan
              </label>
              <select
                value={eEmp}
                onChange={(e) => setEEmp(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                {employments.map((e) => (
                  <option key={e.id} value={e.id}>
                    {personMap.get(e.person_id) ?? "—"}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Kursus
              </label>
              <select
                value={eCourse}
                onChange={(e) => setECourse(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
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
