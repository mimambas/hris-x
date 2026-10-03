"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggal } from "@/lib/format";
import {
  Card,
  EmptyState,
  ErrorBox,
  Field,
  PageHeader,
  Spinner,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

interface MeInfo {
  id: string;
  person_id: string | null;
  is_hr: boolean;
  is_superadmin: boolean;
  roles: string[];
}

interface Skill {
  id: string;
  name: string;
  category: string | null;
  status: string;
  created_at: string;
}

interface ProfileSkill {
  skill_id: string;
  skill_name: string;
  category: string | null;
  proficiency: number;
  skill_status: string;
}

interface Profile {
  employment_id: string;
  person_name: string;
  job_title: string | null;
  org_unit_name: string | null;
  mobility_preference: string;
  career_aspiration: string | null;
  skills: ProfileSkill[];
  pending_skills: ProfileSkill[];
  certifications: {
    course_name: string;
    completed_at: string | null;
    cert_expires_at: string | null;
    certificate_document_id: string | null;
  }[];
  latest_box_key: string | null;
  latest_box_label: string | null;
}

interface Nomination {
  id: string;
  employment_id: string;
  person_name: string;
  readiness: string;
  notes: string | null;
  created_at: string;
}

interface KeyPosition {
  position_id: string;
  position_name: string;
  job_title: string | null;
  org_unit_name: string | null;
  nominations: Nomination[];
  has_ready_successor: boolean;
}

interface Pool {
  id: string;
  name: string;
  cycle_id: string;
  box_keys: string[];
  members: { employment_id: string; person_name: string; box_key: string }[];
  created_at: string;
}

interface CareerPath {
  id: string;
  from_job_id: string;
  from_job_title: string | null;
  to_job_id: string;
  to_job_title: string | null;
  notes: string | null;
}

interface IdpItem {
  id: string;
  title: string;
  course_id: string | null;
  course_name: string | null;
  target_date: string | null;
  status: string;
  notes: string | null;
}

interface Idp {
  id: string;
  employment_id: string;
  person_name: string;
  target_job_id: string | null;
  target_job_title: string | null;
  year: number;
  status: string;
  items: IdpItem[];
}

interface Opportunity {
  id: string;
  kind: string;
  title: string;
  description: string | null;
  org_unit_id: string | null;
  status: string;
  created_at: string;
}

interface Application {
  id: string;
  opportunity_id: string;
  employment_id: string;
  person_name: string;
  status: string;
  cover_note: string | null;
  created_at: string;
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

interface OrgPosition {
  id: string;
  job_id: string;
  org_unit_id: string;
  name: string;
}

interface Course {
  id: string;
  code: string;
  name: string;
}

interface Cycle {
  id: string;
  name: string;
  year: number;
  status: string;
}

const READINESS_LABEL: Record<string, string> = {
  siap_sekarang: "Siap Sekarang",
  siap_1_tahun: "Siap 1 Tahun",
  siap_2_tahun: "Siap 2 Tahun+",
};

const MOBILITY_LABEL: Record<string, string> = {
  tidak_terbuka: "Tidak terbuka relokasi",
  dalam_kota: "Dalam kota",
  luar_kota: "Luar kota",
  semua: "Semua lokasi",
};

const BOX_LABEL: Record<string, string> = {
  star: "Bintang",
  high_performer: "Berkinerja Tinggi",
  trusted_professional: "Profesional Andal",
  high_potential: "Potensi Tinggi",
  key_player: "Pemain Kunci",
  average_performer: "Kinerja Rata-rata",
  rough_diamond: "Berlian Mentah",
  inconsistent_player: "Kinerja Tidak Konsisten",
  low_performer: "Kinerja Rendah",
};

const APP_STATUS_LABEL: Record<string, string> = {
  diajukan: "Diajukan",
  seleksi: "Seleksi",
  diterima: "Diterima",
  ditolak: "Ditolak",
};

export default function SuksesiPage() {
  const [me, setMe] = useState<MeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [softWarn, setSoftWarn] = useState(false);
  const [busy, setBusy] = useState(false);

  const [employments, setEmployments] = useState<Employment[]>([]);
  const [personMap, setPersonMap] = useState<Map<string, string>>(new Map());
  const [jobs, setJobs] = useState<OrgJob[]>([]);
  const [positions, setPositions] = useState<OrgPosition[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [cycles, setCycles] = useState<Cycle[]>([]);

  const [skills, setSkills] = useState<Skill[]>([]);
  const [keyPositions, setKeyPositions] = useState<KeyPosition[] | null>(null);
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [careerPaths, setCareerPaths] = useState<CareerPath[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [myApps, setMyApps] = useState<Application[]>([]);

  // Pilihan karyawan untuk profil & IDP (default: diri sendiri).
  const [selEmp, setSelEmp] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [idps, setIdps] = useState<Idp[]>([]);

  const isHR = !!(me?.is_hr || me?.is_superadmin);
  const empName = useCallback(
    (empId: string) => {
      const e = employments.find((x) => x.id === empId);
      return e ? personMap.get(e.person_id) ?? "?" : "?";
    },
    [employments, personMap]
  );

  const load = useCallback(async (soft = false) => {
    if (!soft) {
      setLoading(true);
      setError(null);
    }
    try {
      const meInfo = await fetchRetry(() => apiFetch<MeInfo>("/me"));
      setMe(meInfo);
      const [emps, persons, jb, ps, cs, cy] = await Promise.all([
        apiFetch<Employment[]>("/employments").catch(() => []),
        apiFetch<Person[]>("/persons").catch(() => []),
        apiFetch<OrgJob[]>("/org/jobs").catch(() => []),
        apiFetch<OrgPosition[]>("/org/positions").catch(() => []),
        apiFetch<Course[]>("/performance/courses").catch(() => []),
        apiFetch<Cycle[]>("/performance/cycles").catch(() => []),
      ]);
      const pm = new Map(persons.map((p) => [p.id, p.full_name]));
      setPersonMap(pm);
      const active = emps.filter(
        (e) => e.status === "active" && pm.has(e.person_id)
      );
      setEmployments(active);
      setJobs(jb);
      setPositions(ps);
      setCourses(cs);
      setCycles(cy);
      const own = active.find((e) => e.person_id === meInfo.person_id);
      setSelEmp((prev) => prev || own?.id || active[0]?.id || "");

      const [sk, cp, op, ma] = await Promise.all([
        apiFetch<Skill[]>("/talent/skills").catch(() => []),
        apiFetch<CareerPath[]>("/talent/career-paths").catch(() => []),
        apiFetch<Opportunity[]>("/talent/opportunities").catch(() => []),
        apiFetch<Application[]>("/talent/applications/mine").catch(() => []),
      ]);
      setSkills(sk);
      setCareerPaths(cp);
      setOpportunities(op);
      setMyApps(ma);
      // Khusus HR: perencanaan suksesi & talent pool (403 -> disembunyikan).
      const [kp, pl] = await Promise.all([
        apiFetch<KeyPosition[]>("/talent/key-positions").catch(() => null),
        apiFetch<Pool[]>("/talent/pools").catch(() => null),
      ]);
      setKeyPositions(kp);
      setPools(pl);
    } catch (err) {
      if (soft) {
        // Mutasi sudah berhasil di server; kegagalan memuat ulang daftar
        // jangan ditampilkan sebagai kegagalan aksi.
        setSoftWarn(true);
      } else {
        setError(
          err instanceof ApiError ? err.message : "Gagal memuat data suksesi."
        );
      }
    } finally {
      if (!soft) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadProfile = useCallback(async () => {
    if (!selEmp) {
      setProfile(null);
      setIdps([]);
      return;
    }
    const [p, il] = await Promise.all([
      fetchRetry(() =>
        apiFetch<Profile>(`/talent/employments/${selEmp}/profile`)
      ).catch(() => null),
      apiFetch<Idp[]>(`/talent/employments/${selEmp}/idps`).catch(() => []),
    ]);
    setProfile(p);
    setIdps(il);
  }, [selEmp]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  async function act(fn: () => Promise<void>, okMsg: string) {
    setBusy(true);
    setMsg(null);
    setError(null);
    setSoftWarn(false);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Aksi gagal.");
      setBusy(false);
      return;
    }
    setMsg(okMsg);
    await load(true);
    await loadProfile();
    setBusy(false);
  }

  if (loading) return <Spinner />;
  if (error && !me) return <ErrorBox message={error} onRetry={load} />;

  return (
    <div>
      <PageHeader
        title="Suksesi & Karier"
        subtitle="Profil talent, posisi kunci & suksesor, talent pool, IDP, dan peluang internal"
      />
      {msg && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {msg}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}
      {softWarn && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <span>
            Aksi tersimpan, tetapi daftar gagal dimuat ulang otomatis.
          </span>
          <button
            className={btnSmall}
            onClick={() => {
              setSoftWarn(false);
              load();
            }}
          >
            Muat ulang
          </button>
        </div>
      )}

      <ProfileSection
        me={me}
        isHR={isHR}
        employments={employments}
        empName={empName}
        selEmp={selEmp}
        setSelEmp={setSelEmp}
        profile={profile}
        skills={skills}
        busy={busy}
        act={act}
      />

      <SkillSection isHR={isHR} skills={skills} busy={busy} act={act} />

      {keyPositions !== null && (
        <SuccessionSection
          keyPositions={keyPositions}
          positions={positions}
          jobs={jobs}
          employments={employments}
          empName={empName}
          busy={busy}
          act={act}
        />
      )}

      {pools !== null && (
        <PoolSection pools={pools} cycles={cycles} busy={busy} act={act} />
      )}

      <CareerSection
        isHR={isHR}
        careerPaths={careerPaths}
        jobs={jobs}
        courses={courses}
        selEmp={selEmp}
        empName={empName}
        idps={idps}
        busy={busy}
        act={act}
      />

      <MarketplaceSection
        isHR={isHR}
        opportunities={opportunities}
        myApps={myApps}
        busy={busy}
        act={act}
      />
    </div>
  );
}


type ActFn = (fn: () => Promise<void>, okMsg: string) => Promise<void>;

// Staging Vercel kadang gagal sesaat (cold start) tepat setelah mutasi:
// lempar satu kali percobaan ulang khusus untuk kegagalan jaringan
// (ApiError status 0) agar daftar termuat ulang tanpa banner menakutkan.
async function fetchRetry<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      await new Promise((r) => setTimeout(r, 1500));
      return await fn();
    }
    throw e;
  }
}

function ProfileSection({
  me,
  isHR,
  employments,
  empName,
  selEmp,
  setSelEmp,
  profile,
  skills,
  busy,
  act,
}: {
  me: MeInfo | null;
  isHR: boolean;
  employments: Employment[];
  empName: (id: string) => string;
  selEmp: string;
  setSelEmp: (v: string) => void;
  profile: Profile | null;
  skills: Skill[];
  busy: boolean;
  act: ActFn;
}) {
  const [mobility, setMobility] = useState("tidak_terbuka");
  const [aspiration, setAspiration] = useState("");
  const [skillId, setSkillId] = useState("");
  const [skillName, setSkillName] = useState("");
  const [proficiency, setProficiency] = useState(3);

  useEffect(() => {
    if (profile) {
      setMobility(profile.mobility_preference);
      setAspiration(profile.career_aspiration ?? "");
    }
  }, [profile]);

  const ownId = employments.find((e) => e.person_id === me?.person_id)?.id;
  const canEdit = isHR || (!!ownId && ownId === selEmp);

  return (
    <Card title="Profil Talent" subtitle="Skill, sertifikasi, mobilitas, dan posisi 9-box terakhir">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Karyawan">
          <select
            className={inputCls}
            value={selEmp}
            onChange={(e) => setSelEmp(e.target.value)}
          >
            {employments.map((e) => (
              <option key={e.id} value={e.id}>
                {empName(e.id)}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {!profile ? (
        <EmptyState message="Profil tidak tersedia (di luar cakupan akses Anda)." />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <div>
              <p className="text-slate-500">Jabatan saat ini</p>
              <p className="font-medium text-slate-900">
                {profile.job_title ?? "-"}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Unit organisasi</p>
              <p className="font-medium text-slate-900">
                {profile.org_unit_name ?? "-"}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Kotak 9-box terakhir</p>
              <p className="font-medium text-slate-900">
                {profile.latest_box_label ?? "Belum ada penilaian"}
              </p>
            </div>
          </div>

          <div>
            <p className="mb-1 text-sm font-medium text-slate-700">
              Skill terverifikasi
            </p>
            {profile.skills.length === 0 ? (
              <p className="text-sm text-slate-400">Belum ada skill terverifikasi.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {profile.skills.map((s) => (
                  <span
                    key={s.skill_id}
                    className="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-200"
                  >
                    {s.skill_name} · level {s.proficiency}
                  </span>
                ))}
              </div>
            )}
            {profile.pending_skills.length > 0 && (
              <p className="mt-2 text-xs text-amber-600">
                Menunggu persetujuan HR:{" "}
                {profile.pending_skills.map((s) => s.skill_name).join(", ")}
              </p>
            )}
          </div>

          <div>
            <p className="mb-1 text-sm font-medium text-slate-700">
              Sertifikasi (dari Pelatihan)
            </p>
            {profile.certifications.length === 0 ? (
              <p className="text-sm text-slate-400">Belum ada sertifikasi.</p>
            ) : (
              <ul className="space-y-1 text-sm text-slate-700">
                {profile.certifications.map((c, i) => (
                  <li key={i}>
                    {c.course_name}
                    {c.cert_expires_at
                      ? ` · berlaku s.d. ${tanggal(c.cert_expires_at)}`
                      : " · tanpa kedaluwarsa"}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {canEdit && (
            <div className="grid grid-cols-1 gap-3 border-t border-slate-100 pt-4 md:grid-cols-2">
              <div className="space-y-3">
                <Field label="Preferensi mobilitas">
                  <select
                    className={inputCls}
                    value={mobility}
                    onChange={(e) => setMobility(e.target.value)}
                  >
                    {Object.entries(MOBILITY_LABEL).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Aspirasi karier">
                  <textarea
                    className={inputCls}
                    rows={2}
                    value={aspiration}
                    onChange={(e) => setAspiration(e.target.value)}
                    placeholder="mis. Menjadi supervisor gudang dalam 2 tahun"
                  />
                </Field>
                <button
                  className={btnPrimary}
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await apiFetch(
                        `/talent/employments/${selEmp}/profile`,
                        {
                          method: "PUT",
                          body: JSON.stringify({
                            mobility_preference: mobility,
                            career_aspiration: aspiration || null,
                          }),
                        }
                      );
                    }, "Profil talent diperbarui.")
                  }
                >
                  Simpan profil
                </button>
              </div>
              <div className="space-y-3">
                <Field label="Tambah skill dari katalog">
                  <select
                    className={inputCls}
                    value={skillId}
                    onChange={(e) => setSkillId(e.target.value)}
                  >
                    <option value="">— pilih skill —</option>
                    {skills.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} ({s.status})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="atau usulkan skill baru">
                  <input
                    className={inputCls}
                    value={skillName}
                    onChange={(e) => setSkillName(e.target.value)}
                    placeholder="mis. Pengoperasian Forklift"
                  />
                </Field>
                <Field label="Tingkat kemahiran (1–5)">
                  <input
                    className={inputCls}
                    type="number"
                    min={1}
                    max={5}
                    value={proficiency}
                    onChange={(e) => setProficiency(Number(e.target.value))}
                  />
                </Field>
                <button
                  className={btnSecondary}
                  disabled={busy || (!skillId && !skillName.trim())}
                  onClick={() =>
                    act(async () => {
                      await apiFetch(
                        `/talent/employments/${selEmp}/skills`,
                        {
                          method: "POST",
                          body: JSON.stringify({
                            skill_id: skillId || null,
                            skill_name: skillId ? null : skillName.trim(),
                            proficiency,
                          }),
                        }
                      );
                      setSkillId("");
                      setSkillName("");
                    }, "Skill ditambahkan ke profil.")
                  }
                >
                  Tambah skill
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function SkillSection({
  isHR,
  skills,
  busy,
  act,
}: {
  isHR: boolean;
  skills: Skill[];
  busy: boolean;
  act: ActFn;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const usulan = skills.filter((s) => s.status === "usulan");
  const disetujui = skills.filter((s) => s.status === "disetujui");

  return (
    <div className="mt-6">
      <Card
        title="Katalog Skill"
        subtitle="Skill baru berstatus usulan sampai disetujui HR (governance SUC-006)"
      >
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label="Nama skill">
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="mis. Analisis Data"
            />
          </Field>
          <Field label="Kategori">
            <input
              className={inputCls}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="mis. Teknis"
            />
          </Field>
          <button
            className={btnPrimary}
            disabled={busy || !name.trim()}
            onClick={() =>
              act(async () => {
                await apiFetch("/talent/skills", {
                  method: "POST",
                  body: JSON.stringify({
                    name: name.trim(),
                    category: category.trim() || null,
                  }),
                });
                setName("");
                setCategory("");
              }, "Skill diusulkan.")
            }
          >
            Usulkan skill
          </button>
        </div>

        {isHR && usulan.length > 0 && (
          <div className="mb-4">
            <p className="mb-2 text-sm font-medium text-amber-700">
              Menunggu persetujuan ({usulan.length})
            </p>
            <ul className="space-y-2">
              {usulan.map((s) => (
                <li
                  key={s.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm ring-1 ring-amber-200"
                >
                  <span>
                    {s.name}
                    {s.category ? ` · ${s.category}` : ""}
                  </span>
                  <span className="flex gap-2">
                    <button
                      className={btnSmall}
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await apiFetch(`/talent/skills/${s.id}/decision`, {
                            method: "POST",
                            body: JSON.stringify({ decision: "setujui" }),
                          });
                        }, `Skill ${s.name} disetujui.`)
                      }
                    >
                      Setujui
                    </button>
                    <button
                      className={btnSmall}
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await apiFetch(`/talent/skills/${s.id}/decision`, {
                            method: "POST",
                            body: JSON.stringify({ decision: "tolak" }),
                          });
                        }, `Skill ${s.name} ditolak.`)
                      }
                    >
                      Tolak
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {disetujui.length === 0 ? (
          <EmptyState message="Belum ada skill yang disetujui." />
        ) : (
          <div className="flex flex-wrap gap-2">
            {disetujui.map((s) => (
              <span
                key={s.id}
                className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
              >
                {s.name}
                {s.category ? ` · ${s.category}` : ""}
              </span>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}


function SuccessionSection({
  keyPositions,
  positions,
  jobs,
  employments,
  empName,
  busy,
  act,
}: {
  keyPositions: KeyPosition[];
  positions: OrgPosition[];
  jobs: OrgJob[];
  employments: Employment[];
  empName: (id: string) => string;
  busy: boolean;
  act: ActFn;
}) {
  const [nomEmp, setNomEmp] = useState<Record<string, string>>({});
  const [nomReadiness, setNomReadiness] = useState<Record<string, string>>({});
  const keyIds = new Set(keyPositions.map((k) => k.position_id));
  const gaps = keyPositions.filter((k) => !k.has_ready_successor);
  const jobTitle = (jobId: string) =>
    jobs.find((j) => j.id === jobId)?.title ?? "";

  return (
    <div className="mt-6">
      <Card
        title="Posisi Kunci & Suksesi"
        subtitle="Khusus HR — posisi kunci tanpa suksesor siap ditandai sebagai celah suksesi"
      >
        {gaps.length > 0 && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {gaps.length} posisi kunci belum punya suksesor “Siap Sekarang”:{" "}
            {gaps.map((g) => g.position_name).join(", ")}
          </div>
        )}

        <div className="mb-5">
          <p className="mb-2 text-sm font-medium text-slate-700">
            Tandai posisi sebagai posisi kunci
          </p>
          <div className="flex flex-wrap gap-2">
            {positions
              .filter((p) => !keyIds.has(p.id))
              .map((p) => (
                <button
                  key={p.id}
                  className={btnSmall}
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await apiFetch(`/talent/positions/${p.id}/key`, {
                        method: "PATCH",
                        body: JSON.stringify({ is_key: true }),
                      });
                    }, `Posisi ${p.name} ditandai kunci.`)
                  }
                >
                  + {p.name} ({jobTitle(p.job_id)})
                </button>
              ))}
            {positions.every((p) => keyIds.has(p.id)) && (
              <p className="text-sm text-slate-400">
                Semua posisi sudah ditandai kunci.
              </p>
            )}
          </div>
        </div>

        {keyPositions.length === 0 ? (
          <EmptyState message="Belum ada posisi kunci." />
        ) : (
          <div className="space-y-4">
            {keyPositions.map((kp) => (
              <div
                key={kp.position_id}
                className="rounded-xl ring-1 ring-slate-200"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
                  <div>
                    <p className="font-medium text-slate-900">
                      {kp.position_name}
                      {kp.job_title ? ` · ${kp.job_title}` : ""}
                    </p>
                    <p className="text-xs text-slate-500">
                      {kp.org_unit_name ?? "-"}
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-medium ${
                      kp.has_ready_successor
                        ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                        : "bg-red-50 text-red-700 ring-1 ring-red-200"
                    }`}
                  >
                    {kp.has_ready_successor
                      ? "Ada suksesor siap"
                      : "CELAH SUKSESI"}
                  </span>
                </div>
                <div className="px-4 py-3">
                  {kp.nominations.length === 0 ? (
                    <p className="text-sm text-slate-400">
                      Belum ada nominasi suksesor.
                    </p>
                  ) : (
                    <ul className="mb-3 space-y-1 text-sm text-slate-700">
                      {kp.nominations.map((n) => (
                        <li key={n.id} className="flex items-center gap-2">
                          <span className="font-medium">{n.person_name}</span>
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                            {READINESS_LABEL[n.readiness] ?? n.readiness}
                          </span>
                          {n.notes && (
                            <span className="text-slate-500">— {n.notes}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="flex flex-wrap items-end gap-2">
                    <select
                      className={`${inputCls} w-auto`}
                      value={nomEmp[kp.position_id] ?? ""}
                      onChange={(e) =>
                        setNomEmp((m) => ({
                          ...m,
                          [kp.position_id]: e.target.value,
                        }))
                      }
                    >
                      <option value="">— pilih karyawan —</option>
                      {employments.map((e) => (
                        <option key={e.id} value={e.id}>
                          {empName(e.id)}
                        </option>
                      ))}
                    </select>
                    <select
                      className={`${inputCls} w-auto`}
                      value={nomReadiness[kp.position_id] ?? "siap_1_tahun"}
                      onChange={(e) =>
                        setNomReadiness((m) => ({
                          ...m,
                          [kp.position_id]: e.target.value,
                        }))
                      }
                    >
                      {Object.entries(READINESS_LABEL).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <button
                      className={btnSmall}
                      disabled={busy || !nomEmp[kp.position_id]}
                      onClick={() =>
                        act(async () => {
                          await apiFetch(
                            `/talent/positions/${kp.position_id}/nominations`,
                            {
                              method: "POST",
                              body: JSON.stringify({
                                employment_id: nomEmp[kp.position_id],
                                readiness:
                                  nomReadiness[kp.position_id] ??
                                  "siap_1_tahun",
                              }),
                            }
                          );
                        }, "Suksesor dinominasikan.")
                      }
                    >
                      Nominasikan
                    </button>
                    <button
                      className={btnSmall}
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await apiFetch(`/talent/positions/${kp.position_id}/key`, {
                            method: "PATCH",
                            body: JSON.stringify({ is_key: false }),
                          });
                        }, `Posisi ${kp.position_name} tidak lagi kunci.`)
                      }
                    >
                      Lepas tanda kunci
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function PoolSection({
  pools,
  cycles,
  busy,
  act,
}: {
  pools: Pool[];
  cycles: Cycle[];
  busy: boolean;
  act: ActFn;
}) {
  const [name, setName] = useState("");
  const [cycleId, setCycleId] = useState("");
  const [boxes, setBoxes] = useState<string[]>(["star", "high_potential"]);

  function toggleBox(k: string) {
    setBoxes((b) => (b.includes(k) ? b.filter((x) => x !== k) : [...b, k]));
  }

  return (
    <div className="mt-6">
      <Card
        title="Talent Pool"
        subtitle="Khusus HR — snapshot anggota dari kotak 9-box satu siklus penilaian"
      >
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Nama pool">
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="mis. Pool Bintang 2026"
            />
          </Field>
          <Field label="Siklus penilaian">
            <select
              className={inputCls}
              value={cycleId}
              onChange={(e) => setCycleId(e.target.value)}
            >
              <option value="">— pilih siklus —</option>
              {cycles.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.status})
                </option>
              ))}
            </select>
          </Field>
          <div className="flex items-end">
            <button
              className={btnPrimary}
              disabled={busy || !name.trim() || !cycleId || boxes.length === 0}
              onClick={() =>
                act(async () => {
                  await apiFetch("/talent/pools", {
                    method: "POST",
                    body: JSON.stringify({
                      name: name.trim(),
                      cycle_id: cycleId,
                      box_keys: boxes,
                    }),
                  });
                  setName("");
                }, "Talent pool dibuat.")
              }
            >
              Buat pool
            </button>
          </div>
        </div>
        <div className="mb-5 flex flex-wrap gap-2">
          {Object.entries(BOX_LABEL).map(([k, v]) => (
            <label
              key={k}
              className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium ring-1 ${
                boxes.includes(k)
                  ? "bg-brand-600 text-white ring-brand-600"
                  : "bg-white text-slate-600 ring-slate-300"
              }`}
            >
              <input
                type="checkbox"
                className="hidden"
                checked={boxes.includes(k)}
                onChange={() => toggleBox(k)}
              />
              {v}
            </label>
          ))}
        </div>

        {pools.length === 0 ? (
          <EmptyState message="Belum ada talent pool." />
        ) : (
          <div className="space-y-3">
            {pools.map((p) => (
              <div key={p.id} className="rounded-xl ring-1 ring-slate-200">
                <div className="border-b border-slate-100 px-4 py-3">
                  <p className="font-medium text-slate-900">{p.name}</p>
                  <p className="text-xs text-slate-500">
                    Kotak: {p.box_keys.map((k) => BOX_LABEL[k] ?? k).join(", ")}{" "}
                    · {p.members.length} anggota
                  </p>
                </div>
                {p.members.length > 0 && (
                  <ul className="space-y-1 px-4 py-3 text-sm text-slate-700">
                    {p.members.map((m) => (
                      <li key={m.employment_id}>
                        {m.person_name}{" "}
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                          {BOX_LABEL[m.box_key] ?? m.box_key}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}


function CareerSection({
  isHR,
  careerPaths,
  jobs,
  courses,
  selEmp,
  empName,
  idps,
  busy,
  act,
}: {
  isHR: boolean;
  careerPaths: CareerPath[];
  jobs: OrgJob[];
  courses: Course[];
  selEmp: string;
  empName: (id: string) => string;
  idps: Idp[];
  busy: boolean;
  act: ActFn;
}) {
  const [fromJob, setFromJob] = useState("");
  const [toJob, setToJob] = useState("");
  const [year, setYear] = useState(new Date().getFullYear() + 1);
  const [targetJob, setTargetJob] = useState("");
  const [itemTitle, setItemTitle] = useState<Record<string, string>>({});
  const [itemCourse, setItemCourse] = useState<Record<string, string>>({});

  return (
    <div className="mt-6">
      <Card
        title="Jalur Karier & IDP"
        subtitle="Rencana pengembangan individu yang terhubung ke kursus Pelatihan"
      >
        <div className="mb-5">
          <p className="mb-2 text-sm font-medium text-slate-700">
            Peta jalur karier
          </p>
          {careerPaths.length === 0 ? (
            <p className="text-sm text-slate-400">Belum ada jalur karier.</p>
          ) : (
            <ul className="mb-3 space-y-1 text-sm text-slate-700">
              {careerPaths.map((p) => (
                <li key={p.id}>
                  {p.from_job_title ?? "?"} → {p.to_job_title ?? "?"}
                  {p.notes && (
                    <span className="text-slate-500"> — {p.notes}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {isHR && (
            <div className="flex flex-wrap items-end gap-2">
              <select
                className={`${inputCls} w-auto`}
                value={fromJob}
                onChange={(e) => setFromJob(e.target.value)}
              >
                <option value="">Jabatan asal</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.title}
                  </option>
                ))}
              </select>
              <select
                className={`${inputCls} w-auto`}
                value={toJob}
                onChange={(e) => setToJob(e.target.value)}
              >
                <option value="">Jabatan tujuan</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.title}
                  </option>
                ))}
              </select>
              <button
                className={btnSmall}
                disabled={busy || !fromJob || !toJob}
                onClick={() =>
                  act(async () => {
                    await apiFetch("/talent/career-paths", {
                      method: "POST",
                      body: JSON.stringify({
                        from_job_id: fromJob,
                        to_job_id: toJob,
                      }),
                    });
                    setFromJob("");
                    setToJob("");
                  }, "Jalur karier ditambahkan.")
                }
              >
                Tambah jalur
              </button>
            </div>
          )}
        </div>

        <div className="border-t border-slate-100 pt-4">
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <p className="text-sm font-medium text-slate-700">
              IDP {selEmp ? empName(selEmp) : ""}
            </p>
            <input
              className={`${inputCls} w-24`}
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            />
            <select
              className={`${inputCls} w-auto`}
              value={targetJob}
              onChange={(e) => setTargetJob(e.target.value)}
            >
              <option value="">Tanpa target jabatan</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  Target: {j.title}
                </option>
              ))}
            </select>
            <button
              className={btnSmall}
              disabled={busy || !selEmp}
              onClick={() =>
                act(async () => {
                  await apiFetch("/talent/idps", {
                    method: "POST",
                    body: JSON.stringify({
                      employment_id: selEmp,
                      target_job_id: targetJob || null,
                      year,
                    }),
                  });
                }, `IDP ${year} dibuat.`)
              }
            >
              Buat IDP
            </button>
          </div>

          {idps.length === 0 ? (
            <EmptyState message="Belum ada IDP untuk karyawan terpilih." />
          ) : (
            <div className="space-y-3">
              {idps.map((idp) => (
                <div key={idp.id} className="rounded-xl ring-1 ring-slate-200">
                  <div className="border-b border-slate-100 px-4 py-3">
                    <p className="font-medium text-slate-900">
                      IDP {idp.year}
                      {idp.target_job_title
                        ? ` · target ${idp.target_job_title}`
                        : ""}
                    </p>
                  </div>
                  <div className="px-4 py-3">
                    {idp.items.length === 0 ? (
                      <p className="mb-2 text-sm text-slate-400">
                        Belum ada item pengembangan.
                      </p>
                    ) : (
                      <ul className="mb-3 space-y-1 text-sm">
                        {idp.items.map((it) => (
                          <li
                            key={it.id}
                            className="flex flex-wrap items-center gap-2"
                          >
                            <button
                              className={btnSmall}
                              disabled={busy}
                              onClick={() =>
                                act(async () => {
                                  await apiFetch(
                                    `/talent/idp-items/${it.id}`,
                                    {
                                      method: "PATCH",
                                      body: JSON.stringify({
                                        status:
                                          it.status === "selesai"
                                            ? "belum"
                                            : "selesai",
                                      }),
                                    }
                                  );
                                }, "Status item IDP diperbarui.")
                              }
                            >
                              {it.status === "selesai" ? "✓" : "○"}
                            </button>
                            <span
                              className={
                                it.status === "selesai"
                                  ? "text-slate-400 line-through"
                                  : "text-slate-700"
                              }
                            >
                              {it.title}
                            </span>
                            {it.course_name && (
                              <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-700">
                                Kursus: {it.course_name}
                              </span>
                            )}
                            {it.target_date && (
                              <span className="text-xs text-slate-500">
                                target {tanggal(it.target_date)}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="flex flex-wrap items-end gap-2">
                      <input
                        className={`${inputCls} w-64`}
                        placeholder="Item pengembangan baru"
                        value={itemTitle[idp.id] ?? ""}
                        onChange={(e) =>
                          setItemTitle((m) => ({
                            ...m,
                            [idp.id]: e.target.value,
                          }))
                        }
                      />
                      <select
                        className={`${inputCls} w-auto`}
                        value={itemCourse[idp.id] ?? ""}
                        onChange={(e) =>
                          setItemCourse((m) => ({
                            ...m,
                            [idp.id]: e.target.value,
                          }))
                        }
                      >
                        <option value="">Tanpa kursus</option>
                        {courses.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.code} — {c.name}
                          </option>
                        ))}
                      </select>
                      <button
                        className={btnSmall}
                        disabled={busy || !(itemTitle[idp.id] ?? "").trim()}
                        onClick={() =>
                          act(async () => {
                            await apiFetch(`/talent/idps/${idp.id}/items`, {
                              method: "POST",
                              body: JSON.stringify({
                                title: (itemTitle[idp.id] ?? "").trim(),
                                course_id: itemCourse[idp.id] || null,
                              }),
                            });
                            setItemTitle((m) => ({ ...m, [idp.id]: "" }));
                          }, "Item IDP ditambahkan.")
                        }
                      >
                        Tambah item
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function MarketplaceSection({
  isHR,
  opportunities,
  myApps,
  busy,
  act,
}: {
  isHR: boolean;
  opportunities: Opportunity[];
  myApps: Application[];
  busy: boolean;
  act: ActFn;
}) {
  const [kind, setKind] = useState("proyek");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [viewOpp, setViewOpp] = useState("");
  const [apps, setApps] = useState<Application[] | null>(null);
  const appliedIds = new Set(myApps.map((a) => a.opportunity_id));

  async function loadApps(oppId: string) {
    setViewOpp(oppId);
    const rows = await apiFetch<Application[]>(
      `/talent/opportunities/${oppId}/applications`
    ).catch(() => []);
    setApps(rows);
  }

  return (
    <div className="mt-6">
      <Card
        title="Peluang Internal"
        subtitle="Proyek, gig, dan lowongan internal — lamaran tidak terlihat atasan Anda sampai tahap seleksi"
      >
        <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-4">
          <Field label="Jenis">
            <select
              className={inputCls}
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              <option value="proyek">Proyek</option>
              <option value="gig">Gig</option>
              <option value="lowongan">Lowongan</option>
            </select>
          </Field>
          <Field label="Judul peluang">
            <input
              className={inputCls}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="mis. Proyek Digitalisasi Arsip"
            />
          </Field>
          <Field label="Deskripsi">
            <input
              className={inputCls}
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Ringkasan singkat"
            />
          </Field>
          <div className="flex items-end">
            <button
              className={btnPrimary}
              disabled={busy || !title.trim()}
              onClick={() =>
                act(async () => {
                  await apiFetch("/talent/opportunities", {
                    method: "POST",
                    body: JSON.stringify({
                      kind,
                      title: title.trim(),
                      description: desc.trim() || null,
                    }),
                  });
                  setTitle("");
                  setDesc("");
                }, "Peluang internal diterbitkan.")
              }
            >
              Terbitkan peluang
            </button>
          </div>
        </div>

        {opportunities.length === 0 ? (
          <EmptyState message="Belum ada peluang internal yang terbuka." />
        ) : (
          <div className="space-y-3">
            {opportunities.map((o) => (
              <div key={o.id} className="rounded-xl ring-1 ring-slate-200">
                <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                  <div>
                    <p className="font-medium text-slate-900">
                      {o.title}{" "}
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs capitalize text-slate-600">
                        {o.kind}
                      </span>{" "}
                      {o.status === "ditutup" && (
                        <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">
                          Ditutup
                        </span>
                      )}
                    </p>
                    {o.description && (
                      <p className="mt-0.5 text-sm text-slate-500">
                        {o.description}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {o.status === "terbuka" &&
                      (appliedIds.has(o.id) ? (
                        <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
                          Sudah dilamar
                        </span>
                      ) : (
                        <button
                          className={btnSmall}
                          disabled={busy}
                          onClick={() =>
                            act(async () => {
                              await apiFetch(
                                `/talent/opportunities/${o.id}/apply`,
                                {
                                  method: "POST",
                                  body: JSON.stringify({}),
                                }
                              );
                            }, "Lamaran terkirim. Atasan Anda belum dapat melihatnya sampai tahap seleksi.")
                          }
                        >
                          Lamar
                        </button>
                      ))}
                    <button
                      className={btnSmall}
                      onClick={() => loadApps(o.id)}
                    >
                      Lihat lamaran
                    </button>
                    {isHR && o.status === "terbuka" && (
                      <button
                        className={btnSmall}
                        disabled={busy}
                        onClick={() =>
                          act(async () => {
                            await apiFetch(
                              `/talent/opportunities/${o.id}/close`,
                              { method: "POST" }
                            );
                          }, "Peluang ditutup.")
                        }
                      >
                        Tutup
                      </button>
                    )}
                  </div>
                </div>
                {viewOpp === o.id && (
                  <div className="border-t border-slate-100 px-4 py-3">
                    {apps === null || apps.length === 0 ? (
                      <p className="text-sm text-slate-400">
                        Tidak ada lamaran yang dapat Anda lihat untuk peluang
                        ini.
                      </p>
                    ) : (
                      <ul className="space-y-2 text-sm">
                        {apps.map((a) => (
                          <li
                            key={a.id}
                            className="flex flex-wrap items-center justify-between gap-2"
                          >
                            <span>
                              <span className="font-medium">
                                {a.person_name}
                              </span>{" "}
                              · {APP_STATUS_LABEL[a.status] ?? a.status}
                              {a.cover_note ? ` — ${a.cover_note}` : ""}
                            </span>
                            {isHR &&
                              a.status !== "diterima" &&
                              a.status !== "ditolak" && (
                                <span className="flex gap-2">
                                  {a.status === "diajukan" && (
                                    <button
                                      className={btnSmall}
                                      disabled={busy}
                                      onClick={() =>
                                        act(async () => {
                                          await apiFetch(
                                            `/talent/applications/${a.id}/decision`,
                                            {
                                              method: "POST",
                                              body: JSON.stringify({
                                                status: "seleksi",
                                              }),
                                            }
                                          );
                                          await loadApps(o.id);
                                        }, "Lamaran masuk tahap seleksi.")
                                      }
                                    >
                                      Ke seleksi
                                    </button>
                                  )}
                                  {a.status === "seleksi" && (
                                    <button
                                      className={btnSmall}
                                      disabled={busy}
                                      onClick={() =>
                                        act(async () => {
                                          await apiFetch(
                                            `/talent/applications/${a.id}/decision`,
                                            {
                                              method: "POST",
                                              body: JSON.stringify({
                                                status: "diterima",
                                              }),
                                            }
                                          );
                                          await loadApps(o.id);
                                        }, "Lamaran diterima.")
                                      }
                                    >
                                      Terima
                                    </button>
                                  )}
                                  <button
                                    className={btnSmall}
                                    disabled={busy}
                                    onClick={() =>
                                      act(async () => {
                                        await apiFetch(
                                          `/talent/applications/${a.id}/decision`,
                                          {
                                            method: "POST",
                                            body: JSON.stringify({
                                              status: "ditolak",
                                            }),
                                          }
                                        );
                                        await loadApps(o.id);
                                      }, "Lamaran ditolak.")
                                    }
                                  >
                                    Tolak
                                  </button>
                                </span>
                              )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {myApps.length > 0 && (
          <div className="mt-5 border-t border-slate-100 pt-4">
            <p className="mb-2 text-sm font-medium text-slate-700">
              Lamaran saya
            </p>
            <ul className="space-y-1 text-sm text-slate-700">
              {myApps.map((a) => {
                const opp = opportunities.find(
                  (o) => o.id === a.opportunity_id
                );
                return (
                  <li key={a.id}>
                    {opp?.title ?? "Peluang"} —{" "}
                    {APP_STATUS_LABEL[a.status] ?? a.status}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
