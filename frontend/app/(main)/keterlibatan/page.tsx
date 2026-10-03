"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggal, tanggalWaktu } from "@/lib/format";
import { useAuth } from "@/components/AuthContext";
import {
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Modal,
  PageHeader,
  Spinner,
  btnDanger,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
} from "@/components/ui";

// ------------------------------------------------------------- tipe data
interface Announcement {
  id: string;
  title: string;
  body: string;
  target_type: string;
  target_org_unit_id: string | null;
  org_unit_name: string | null;
  published_at: string;
  read_by_me: boolean;
  read_count: number;
  target_count: number;
}

interface AnnouncementReader {
  employment_id: string;
  person_name: string;
  read_at: string | null;
}

interface Survey {
  id: string;
  kind: "enps" | "pulse";
  title: string;
  question: string;
  status: string;
  created_at: string;
  answered_by_me: boolean;
  response_count: number;
}

interface SurveyResult {
  survey_id: string;
  kind: string;
  response_count: number;
  enough_responses: boolean;
  average: number | null;
  enps: number | null;
  distribution: Record<string, number>;
}

interface Kudos {
  id: string;
  from_employment_id: string;
  from_name: string | null;
  to_employment_id: string;
  to_name: string | null;
  category: string;
  message: string;
  visible_on_profile: boolean;
  created_at: string;
}

interface Ticket {
  id: string;
  requester_employment_id: string;
  requester_name: string | null;
  category: string;
  subject: string;
  description: string;
  status: string;
  sla_due_at: string | null;
  sla_breached: boolean;
  resolved_at: string | null;
  created_at: string;
  message_count: number;
}

interface TicketMessage {
  id: string;
  ticket_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

interface KbArticle {
  id: string;
  category: string;
  title: string;
  body: string;
  keywords: string | null;
}

interface KudosCandidate {
  employment_id: string;
  person_name: string;
}

interface OrgUnitLite {
  id: string;
  name: string;
}

const KUDOS_CATEGORIES: { value: string; label: string; icon: string }[] = [
  { value: "kolaborasi", label: "Kolaborasi", icon: "🤝" },
  { value: "inovasi", label: "Inovasi", icon: "💡" },
  { value: "kepemimpinan", label: "Kepemimpinan", icon: "🧭" },
  { value: "pelayanan", label: "Pelayanan", icon: "💛" },
  { value: "keandalan", label: "Keandalan", icon: "🛡️" },
  { value: "lainnya", label: "Lainnya", icon: "🌟" },
];

const TICKET_CATEGORIES: { value: string; label: string }[] = [
  { value: "payroll", label: "Gaji & Payroll" },
  { value: "cuti", label: "Cuti" },
  { value: "absensi", label: "Absensi" },
  { value: "dokumen", label: "Dokumen & Surat" },
  { value: "fasilitas", label: "Fasilitas Kantor" },
  { value: "akun", label: "Akun & Akses" },
  { value: "sistem", label: "Sistem / Aplikasi" },
  { value: "lainnya", label: "Lainnya" },
];

const TICKET_STATUS: Record<string, { label: string; cls: string }> = {
  baru: { label: "Baru", cls: "bg-sky-100 text-sky-800" },
  diproses: { label: "Diproses", cls: "bg-amber-100 text-amber-800" },
  menunggu: { label: "Menunggu info", cls: "bg-violet-100 text-violet-800" },
  selesai: { label: "Selesai", cls: "bg-emerald-100 text-emerald-800" },
  ditutup: { label: "Ditutup", cls: "bg-slate-200 text-slate-600" },
};

type Tab = "pengumuman" | "survei" | "kudos" | "helpdesk";

export default function KeterlibatanPage() {
  const { user } = useAuth();
  const isHr = Boolean(user?.is_hr || user?.is_superadmin);

  const [tab, setTab] = useState<Tab>("pengumuman");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [kudosFeed, setKudosFeed] = useState<Kudos[]>([]);
  const [kudosMine, setKudosMine] = useState<Kudos[]>([]);
  const [myTickets, setMyTickets] = useState<Ticket[]>([]);
  const [allTickets, setAllTickets] = useState<Ticket[]>([]);
  const [kbArticles, setKbArticles] = useState<KbArticle[]>([]);
  const [kudosCandidates, setKudosCandidates] = useState<KudosCandidate[]>([]);
  const [orgUnits, setOrgUnits] = useState<OrgUnitLite[]>([]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [
        ann,
        surv,
        feed,
        mine,
        tickets,
        kb,
        cand,
        units,
      ] = await Promise.all([
        apiFetch<Announcement[]>("/announcements").catch(() => []),
        apiFetch<Survey[]>("/surveys").catch(() => []),
        apiFetch<Kudos[]>("/kudos/feed").catch(() => []),
        apiFetch<Kudos[]>("/kudos/mine").catch(() => []),
        apiFetch<Ticket[]>("/tickets/mine").catch(() => []),
        apiFetch<KbArticle[]>("/kb/articles").catch(() => []),
        apiFetch<KudosCandidate[]>("/kudos/candidates").catch(() => []),
        apiFetch<OrgUnitLite[]>("/org/units").catch(() => []),
      ]);
      setAnnouncements(ann);
      setSurveys(surv);
      setKudosFeed(feed);
      setKudosMine(mine);
      setMyTickets(tickets);
      setKbArticles(kb);
      setKudosCandidates(cand);
      setOrgUnits(units);
      if (isHr) {
        const all = await apiFetch<Ticket[]>("/tickets").catch(() => []);
        setAllTickets(all);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat data.");
    } finally {
      setLoading(false);
    }
  }, [isHr]);

  useEffect(() => {
    void load();
  }, [load]);

  const unreadCount = announcements.filter((a) => !a.read_by_me).length;
  const myOpenTickets = myTickets.filter(
    (t) => t.status !== "selesai" && t.status !== "ditutup"
  ).length;

  const tabs: { key: Tab; label: string; icon: string; badge?: number }[] = [
    { key: "pengumuman", label: "Pengumuman", icon: "📢", badge: unreadCount },
    { key: "survei", label: "Survei", icon: "📊" },
    { key: "kudos", label: "Kudos", icon: "🏆" },
    { key: "helpdesk", label: "Helpdesk & KB", icon: "🎧", badge: myOpenTickets },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Keterlibatan"
        subtitle="Pengumuman perusahaan, survei karyawan, apresiasi antarrekan, dan bantuan HR dalam satu tempat."
      />

      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {actionError && <ErrorBox message={actionError} />}

      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? "bg-brand-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            <span aria-hidden>{t.icon}</span> {t.label}
            {t.badge ? (
              <span className="ml-2 rounded-full bg-rose-500 px-2 py-0.5 text-[11px] font-bold text-white">
                {t.badge}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <>
          {tab === "pengumuman" && (
            <PengumumanTab
              announcements={announcements}
              orgUnits={orgUnits}
              isHr={isHr}
              reload={load}
              setNotice={setNotice}
              setActionError={setActionError}
            />
          )}
          {tab === "survei" && (
            <SurveiTab
              surveys={surveys}
              isHr={isHr}
              reload={load}
              setNotice={setNotice}
              setActionError={setActionError}
            />
          )}
          {tab === "kudos" && (
            <KudosTab
              feed={kudosFeed}
              mine={kudosMine}
              candidates={kudosCandidates}
              reload={load}
              setNotice={setNotice}
              setActionError={setActionError}
            />
          )}
          {tab === "helpdesk" && (
            <HelpdeskTab
              myTickets={myTickets}
              allTickets={allTickets}
              kbArticles={kbArticles}
              isHr={isHr}
              reload={load}
              setNotice={setNotice}
              setActionError={setActionError}
            />
          )}
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------- Pengumuman
function PengumumanTab({
  announcements,
  orgUnits,
  isHr,
  reload,
  setNotice,
  setActionError,
}: {
  announcements: Announcement[];
  orgUnits: OrgUnitLite[];
  isHr: boolean;
  reload: () => Promise<void>;
  setNotice: (s: string | null) => void;
  setActionError: (s: string | null) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [targetType, setTargetType] = useState("semua");
  const [targetOu, setTargetOu] = useState("");
  const [saving, setSaving] = useState(false);
  const [readersOf, setReadersOf] = useState<Announcement | null>(null);
  const [readers, setReaders] = useState<AnnouncementReader[]>([]);
  const [loadingReaders, setLoadingReaders] = useState(false);

  async function markRead(a: Announcement) {
    try {
      await apiFetch(`/announcements/${a.id}/read`, { method: "POST" });
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menandai.");
    }
  }

  async function create() {
    if (title.trim().length < 3 || body.trim().length < 3) {
      setActionError("Judul dan isi pengumuman wajib diisi.");
      return;
    }
    if (targetType === "org_unit" && !targetOu) {
      setActionError("Pilih unit organisasi tujuan.");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await apiFetch("/announcements", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          body: body.trim(),
          target_type: targetType,
          target_org_unit_id: targetType === "org_unit" ? targetOu : null,
        }),
      });
      setNotice("Pengumuman diterbitkan.");
      setTitle("");
      setBody("");
      setTargetType("semua");
      setTargetOu("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menerbitkan.");
    } finally {
      setSaving(false);
    }
  }

  async function openReaders(a: Announcement) {
    setReadersOf(a);
    setLoadingReaders(true);
    try {
      const rows = await apiFetch<AnnouncementReader[]>(
        `/announcements/${a.id}/readers`
      );
      setReaders(rows);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal memuat pembaca.");
    } finally {
      setLoadingReaders(false);
    }
  }

  return (
    <div className="space-y-6">
      {isHr && (
        <Card title="Buat pengumuman">
          <div className="grid gap-4">
            <Field label="Judul">
              <input
                className={inputCls}
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="cth. Jadwal maintenance sistem akhir pekan"
              />
            </Field>
            <Field label="Isi pengumuman">
              <textarea
                className={inputCls}
                rows={4}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Tulis isi pengumuman untuk karyawan…"
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Ditujukan ke">
                <select
                  className={inputCls}
                  value={targetType}
                  onChange={(e) => setTargetType(e.target.value)}
                >
                  <option value="semua">Semua karyawan</option>
                  <option value="org_unit">Unit organisasi tertentu</option>
                </select>
              </Field>
              {targetType === "org_unit" && (
                <Field label="Unit organisasi">
                  <select
                    className={inputCls}
                    value={targetOu}
                    onChange={(e) => setTargetOu(e.target.value)}
                  >
                    <option value="">— Pilih unit —</option>
                    {orgUnits.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>
            <div>
              <button
                className={btnPrimary}
                disabled={saving}
                onClick={() => void create()}
              >
                {saving ? "Menerbitkan…" : "Terbitkan pengumuman"}
              </button>
            </div>
          </div>
        </Card>
      )}

      <Card title={`Pengumuman (${announcements.length})`}>
        {announcements.length === 0 ? (
          <EmptyState message="Belum ada pengumuman untuk Anda." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {announcements.map((a) => (
              <li key={a.id} className="py-4">
                <div className="flex flex-wrap items-start gap-2">
                  <p className="flex-1 text-sm font-semibold text-slate-800">
                    {!a.read_by_me && (
                      <span className="mr-2 inline-block h-2 w-2 rounded-full bg-rose-500 align-middle" />
                    )}
                    {a.title}
                  </p>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    {a.target_type === "semua"
                      ? "Semua karyawan"
                      : `Unit: ${a.org_unit_name ?? "—"}`}
                  </span>
                  <span className="text-xs text-slate-400">
                    {tanggalWaktu(a.published_at)}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
                  {a.body}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {a.read_by_me ? (
                    <span className="text-xs font-medium text-emerald-700">
                      ✓ Sudah dibaca
                    </span>
                  ) : (
                    <button className={btnSmall} onClick={() => void markRead(a)}>
                      Tandai sudah dibaca
                    </button>
                  )}
                  <span className="text-xs text-slate-400">
                    Dibaca {a.read_count} dari {a.target_count} karyawan
                  </span>
                  {isHr && (
                    <button
                      className={btnSmall}
                      onClick={() => void openReaders(a)}
                    >
                      Lihat siapa yang membaca
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {readersOf && (
        <Modal
          title={`Pembaca: ${readersOf.title}`}
          onClose={() => setReadersOf(null)}
          actions={
            <button className={btnSecondary} onClick={() => setReadersOf(null)}>
              Tutup
            </button>
          }
        >
          {loadingReaders ? (
            <Spinner />
          ) : readers.length === 0 ? (
            <EmptyState message="Tidak ada data pembaca." />
          ) : (
            <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
              {readers.map((r) => (
                <li
                  key={r.employment_id}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span className="text-slate-800">{r.person_name}</span>
                  {r.read_at ? (
                    <span className="text-xs text-emerald-700">
                      Dibaca {tanggalWaktu(r.read_at)}
                    </span>
                  ) : (
                    <span className="text-xs font-medium text-rose-600">
                      Belum membaca
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </div>
  );
}

// ----------------------------------------------------------------- Survei
function SurveiTab({
  surveys,
  isHr,
  reload,
  setNotice,
  setActionError,
}: {
  surveys: Survey[];
  isHr: boolean;
  reload: () => Promise<void>;
  setNotice: (s: string | null) => void;
  setActionError: (s: string | null) => void;
}) {
  const [kind, setKind] = useState("enps");
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [saving, setSaving] = useState(false);

  const [score, setScore] = useState<Record<string, number>>({});
  const [comment, setComment] = useState<Record<string, string>>({});
  const [answering, setAnswering] = useState<string | null>(null);

  const [resultOf, setResultOf] = useState<Survey | null>(null);
  const [result, setResult] = useState<SurveyResult | null>(null);
  const [closing, setClosing] = useState<Survey | null>(null);

  async function create() {
    if (title.trim().length < 3 || question.trim().length < 5) {
      setActionError("Judul dan pertanyaan survei wajib diisi.");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await apiFetch("/surveys", {
        method: "POST",
        body: JSON.stringify({ kind, title: title.trim(), question: question.trim() }),
      });
      setNotice("Survei diterbitkan. Jawaban karyawan bersifat anonim.");
      setTitle("");
      setQuestion("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal membuat survei.");
    } finally {
      setSaving(false);
    }
  }

  async function answer(s: Survey) {
    const sc = score[s.id];
    if (sc === undefined) {
      setActionError("Pilih skor dulu sebelum mengirim jawaban.");
      return;
    }
    setAnswering(s.id);
    setActionError(null);
    try {
      await apiFetch(`/surveys/${s.id}/answer`, {
        method: "POST",
        body: JSON.stringify({ score: sc, comment: comment[s.id] || null }),
      });
      setNotice("Terima kasih! Jawaban Anda terekam secara anonim.");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengirim jawaban.");
    } finally {
      setAnswering(null);
    }
  }

  async function openResult(s: Survey) {
    setResultOf(s);
    setResult(null);
    try {
      const r = await apiFetch<SurveyResult>(`/surveys/${s.id}/results`);
      setResult(r);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal memuat hasil.");
    }
  }

  async function closeSurvey(s: Survey) {
    try {
      await apiFetch(`/surveys/${s.id}/close`, { method: "POST" });
      setNotice("Survei ditutup.");
      setClosing(null);
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menutup survei.");
    }
  }

  const scoreRange = (k: string) => (k === "enps" ? 10 : 5);

  return (
    <div className="space-y-6">
      {isHr && (
        <Card title="Buat survei baru">
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Jenis survei">
                <select
                  className={inputCls}
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="enps">eNPS (skor 0–10)</option>
                  <option value="pulse">Pulse (skor 1–5)</option>
                </select>
              </Field>
              <Field label="Judul">
                <input
                  className={inputCls}
                  value={title}
                  maxLength={200}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="cth. eNPS Kuartal Ini"
                />
              </Field>
            </div>
            <Field label="Pertanyaan">
              <input
                className={inputCls}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="cth. Seberapa besar kemungkinan Anda merekomendasikan tempat kerja ini?"
              />
            </Field>
            <div>
              <button
                className={btnPrimary}
                disabled={saving}
                onClick={() => void create()}
              >
                {saving ? "Menerbitkan…" : "Terbitkan survei"}
              </button>
            </div>
          </div>
        </Card>
      )}

      <Card title={`Survei (${surveys.length})`}>
        {surveys.length === 0 ? (
          <EmptyState message="Belum ada survei yang berjalan." />
        ) : (
          <ul className="divide-y divide-slate-100">
            {surveys.map((s) => {
              const max = scoreRange(s.kind);
              const min = s.kind === "enps" ? 0 : 1;
              const chosen = score[s.id];
              return (
                <li key={s.id} className="py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="flex-1 text-sm font-semibold text-slate-800">
                      {s.title}
                    </p>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                      {s.kind === "enps" ? "eNPS" : "Pulse"}
                    </span>
                    {s.status === "aktif" ? (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                        Berjalan
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                        Ditutup
                      </span>
                    )}
                    <span className="text-xs text-slate-400">
                      {s.response_count} jawaban
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-slate-600">{s.question}</p>

                  {s.status === "aktif" &&
                    (s.answered_by_me ? (
                      <p className="mt-2 text-xs font-medium text-emerald-700">
                        ✓ Anda sudah menjawab survei ini (anonim)
                      </p>
                    ) : (
                      <div className="mt-3 space-y-2">
                        <div className="flex flex-wrap gap-1.5">
                          {Array.from({ length: max - min + 1 }, (_, i) => min + i).map(
                            (n) => (
                              <button
                                key={n}
                                onClick={() =>
                                  setScore((prev) => ({ ...prev, [s.id]: n }))
                                }
                                className={`h-9 w-9 rounded-lg text-sm font-semibold transition-colors ${
                                  chosen === n
                                    ? "bg-brand-600 text-white"
                                    : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                                }`}
                                aria-label={`Skor ${n}`}
                              >
                                {n}
                              </button>
                            )
                          )}
                        </div>
                        <input
                          className={inputCls}
                          value={comment[s.id] ?? ""}
                          maxLength={2000}
                          onChange={(e) =>
                            setComment((prev) => ({ ...prev, [s.id]: e.target.value }))
                          }
                          placeholder="Komentar (opsional, tetap anonim)"
                        />
                        <button
                          className={btnPrimary}
                          disabled={answering === s.id}
                          onClick={() => void answer(s)}
                        >
                          {answering === s.id ? "Mengirim…" : "Kirim jawaban anonim"}
                        </button>
                      </div>
                    ))}

                  {isHr && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button className={btnSmall} onClick={() => void openResult(s)}>
                        Lihat hasil
                      </button>
                      {s.status === "aktif" && (
                        <button className={btnSmall} onClick={() => setClosing(s)}>
                          Tutup survei
                        </button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {resultOf && (
        <Modal
          title={`Hasil: ${resultOf.title}`}
          onClose={() => setResultOf(null)}
          actions={
            <button className={btnSecondary} onClick={() => setResultOf(null)}>
              Tutup
            </button>
          }
        >
          {!result ? (
            <Spinner />
          ) : !result.enough_responses ? (
            <p className="text-sm text-slate-600">
              Hasil agregat baru ditampilkan setelah minimal 5 responden demi
              menjaga anonimitas. Saat ini baru {result.response_count} jawaban.
            </p>
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-slate-700">
                Responden: <strong>{result.response_count}</strong>
                {result.average !== null && (
                  <>
                    {" "}· Rata-rata: <strong>{result.average}</strong>
                  </>
                )}
                {result.enps !== null && (
                  <>
                    {" "}· Skor eNPS:{" "}
                    <strong
                      className={
                        result.enps >= 0 ? "text-emerald-700" : "text-rose-600"
                      }
                    >
                      {result.enps}
                    </strong>
                  </>
                )}
              </p>
              <div className="space-y-1">
                {Object.entries(result.distribution)
                  .sort((a, b) => Number(a[0]) - Number(b[0]))
                  .map(([skor, n]) => {
                    const pct = Math.round((n / result.response_count) * 100);
                    return (
                      <div key={skor} className="flex items-center gap-2">
                        <span className="w-10 text-xs text-slate-500">
                          Skor {skor}
                        </span>
                        <div className="h-4 flex-1 rounded bg-slate-100">
                          <div
                            className="h-4 rounded bg-brand-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-14 text-xs text-slate-600">
                          {n} ({pct}%)
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}
        </Modal>
      )}

      {closing && (
        <Modal
          title="Tutup survei?"
          onClose={() => setClosing(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setClosing(null)}>
                Batal
              </button>
              <button className={btnPrimary} onClick={() => void closeSurvey(closing)}>
                Ya, tutup
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            Survei “{closing.title}” tidak lagi menerima jawaban. Hasil yang
            sudah terkumpul tetap dapat dilihat.
          </p>
        </Modal>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Kudos
function KudosTab({
  feed,
  mine,
  candidates,
  reload,
  setNotice,
  setActionError,
}: {
  feed: Kudos[];
  mine: Kudos[];
  candidates: KudosCandidate[];
  reload: () => Promise<void>;
  setNotice: (s: string | null) => void;
  setActionError: (s: string | null) => void;
}) {
  const [toId, setToId] = useState("");
  const [category, setCategory] = useState("kolaborasi");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);

  const catMeta = (v: string) =>
    KUDOS_CATEGORIES.find((c) => c.value === v) ?? KUDOS_CATEGORIES[5];

  async function give() {
    if (!toId) {
      setActionError("Pilih rekan yang ingin diberi kudos.");
      return;
    }
    if (message.trim().length < 3) {
      setActionError("Tulis pesan apresiasi (minimal 3 karakter).");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await apiFetch("/kudos", {
        method: "POST",
        body: JSON.stringify({
          to_employment_id: toId,
          category,
          message: message.trim(),
        }),
      });
      setNotice("Kudos terkirim. Terima kasih sudah mengapresiasi rekan kerja!");
      setToId("");
      setMessage("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengirim kudos.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleVisibility(k: Kudos) {
    setToggling(k.id);
    try {
      await apiFetch(`/kudos/${k.id}/visibility`, {
        method: "PATCH",
        body: JSON.stringify({ visible_on_profile: !k.visible_on_profile }),
      });
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengubah visibilitas.");
    } finally {
      setToggling(null);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Beri kudos ke rekan kerja">
        <div className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Untuk">
              <select
                className={inputCls}
                value={toId}
                onChange={(e) => setToId(e.target.value)}
              >
                <option value="">— Pilih rekan —</option>
                {candidates.map((c) => (
                  <option key={c.employment_id} value={c.employment_id}>
                    {c.person_name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Kategori">
              <select
                className={inputCls}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {KUDOS_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.icon} {c.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Pesan apresiasi">
            <textarea
              className={inputCls}
              rows={3}
              maxLength={1000}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="cth. Makasih banyak sudah bantu lembur revisi desain kemarin!"
            />
          </Field>
          <div>
            <button
              className={btnPrimary}
              disabled={saving}
              onClick={() => void give()}
            >
              {saving ? "Mengirim…" : "Kirim kudos 🏆"}
            </button>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Papan apresiasi">
          {feed.length === 0 ? (
            <EmptyState message="Belum ada kudos. Jadilah yang pertama mengapresiasi rekan!" />
          ) : (
            <ul className="divide-y divide-slate-100">
              {feed.map((k) => (
                <li key={k.id} className="py-3">
                  <p className="text-sm text-slate-800">
                    <span aria-hidden>{catMeta(k.category).icon}</span>{" "}
                    <strong>{k.from_name ?? "—"}</strong> →{" "}
                    <strong>{k.to_name ?? "—"}</strong>
                    <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                      {catMeta(k.category).label}
                    </span>
                  </p>
                  <p className="mt-1 text-sm text-slate-600">{k.message}</p>
                  <p className="text-xs text-slate-400">
                    {tanggalWaktu(k.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Kudos untuk saya">
          {mine.length === 0 ? (
            <EmptyState message="Belum ada kudos masuk untuk Anda." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {mine.map((k) => (
                <li key={k.id} className="py-3">
                  <p className="text-sm text-slate-800">
                    <span aria-hidden>{catMeta(k.category).icon}</span> Dari{" "}
                    <strong>{k.from_name ?? "—"}</strong>
                    <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                      {catMeta(k.category).label}
                    </span>
                  </p>
                  <p className="mt-1 text-sm text-slate-600">{k.message}</p>
                  <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={k.visible_on_profile}
                      disabled={toggling === k.id}
                      onChange={() => void toggleVisibility(k)}
                    />
                    Tampilkan di profil saya
                  </label>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- Helpdesk
function HelpdeskTab({
  myTickets,
  allTickets,
  kbArticles,
  isHr,
  reload,
  setNotice,
  setActionError,
}: {
  myTickets: Ticket[];
  allTickets: Ticket[];
  kbArticles: KbArticle[];
  isHr: boolean;
  reload: () => Promise<void>;
  setNotice: (s: string | null) => void;
  setActionError: (s: string | null) => void;
}) {
  const [kbQuery, setKbQuery] = useState("");
  const [kbResults, setKbResults] = useState<KbArticle[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [openArticle, setOpenArticle] = useState<KbArticle | null>(null);

  const [category, setCategory] = useState("akun");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  const [detail, setDetail] = useState<Ticket | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);

  // Form artikel KB (HR).
  const [kbCat, setKbCat] = useState("akun");
  const [kbTitle, setKbTitle] = useState("");
  const [kbBody, setKbBody] = useState("");
  const [kbKeywords, setKbKeywords] = useState("");
  const [savingKb, setSavingKb] = useState(false);
  const [deletingKb, setDeletingKb] = useState<KbArticle | null>(null);

  async function searchKb() {
    setSearching(true);
    try {
      const rows = await apiFetch<KbArticle[]>(
        `/kb/articles?q=${encodeURIComponent(kbQuery)}`
      );
      setKbResults(rows);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Pencarian gagal.");
    } finally {
      setSearching(false);
    }
  }

  async function createTicket() {
    if (subject.trim().length < 5 || description.trim().length < 10) {
      setActionError("Subjek minimal 5 karakter dan deskripsi minimal 10 karakter.");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await apiFetch("/tickets", {
        method: "POST",
        body: JSON.stringify({
          category,
          subject: subject.trim(),
          description: description.trim(),
        }),
      });
      setNotice("Tiket terkirim. Tim HR akan menindaklanjuti sesuai target layanan (SLA) kategorinya.");
      setSubject("");
      setDescription("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal membuat tiket.");
    } finally {
      setSaving(false);
    }
  }

  async function openTicket(t: Ticket) {
    setDetail(t);
    setReply("");
    try {
      const msgs = await apiFetch<TicketMessage[]>(`/tickets/${t.id}/messages`);
      setMessages(msgs);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal memuat percakapan.");
    }
  }

  async function sendReply() {
    if (!detail || reply.trim() === "") return;
    setSending(true);
    try {
      await apiFetch(`/tickets/${detail.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ body: reply.trim() }),
      });
      const msgs = await apiFetch<TicketMessage[]>(
        `/tickets/${detail.id}/messages`
      );
      setMessages(msgs);
      setReply("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengirim pesan.");
    } finally {
      setSending(false);
    }
  }

  async function changeStatus(t: Ticket, newStatus: string) {
    try {
      await apiFetch(`/tickets/${t.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      });
      setNotice(`Status tiket diperbarui menjadi ${TICKET_STATUS[newStatus]?.label ?? newStatus}.`);
      await reload();
      if (detail?.id === t.id) {
        const fresh = await apiFetch<Ticket>(`/tickets/${t.id}`);
        setDetail(fresh);
      }
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengubah status.");
    }
  }

  async function createKb() {
    if (kbTitle.trim().length < 5 || kbBody.trim().length < 10) {
      setActionError("Judul artikel minimal 5 karakter dan isi minimal 10 karakter.");
      return;
    }
    setSavingKb(true);
    setActionError(null);
    try {
      await apiFetch("/kb/articles", {
        method: "POST",
        body: JSON.stringify({
          category: kbCat,
          title: kbTitle.trim(),
          body: kbBody.trim(),
          keywords: kbKeywords.trim() || null,
        }),
      });
      setNotice("Artikel basis pengetahuan diterbitkan.");
      setKbTitle("");
      setKbBody("");
      setKbKeywords("");
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menyimpan artikel.");
    } finally {
      setSavingKb(false);
    }
  }

  async function deleteKb(a: KbArticle) {
    try {
      await apiFetch(`/kb/articles/${a.id}`, { method: "DELETE" });
      setNotice("Artikel dihapus.");
      setDeletingKb(null);
      await reload();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menghapus artikel.");
    }
  }

  const shownKb = kbResults ?? kbArticles;

  function ticketRow(t: Ticket, showRequester: boolean) {
    const st = TICKET_STATUS[t.status] ?? TICKET_STATUS.baru;
    return (
      <li key={t.id} className="py-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="flex-1 text-left text-sm font-medium text-slate-800 hover:underline"
            onClick={() => void openTicket(t)}
          >
            {t.subject}
          </button>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}
          >
            {st.label}
          </span>
          {t.sla_breached && (
            <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-700">
              Lewat SLA
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {TICKET_CATEGORIES.find((c) => c.value === t.category)?.label ??
            t.category}
          {showRequester && t.requester_name ? ` · ${t.requester_name}` : ""}
          {" · "}
          {tanggal(t.created_at.slice(0, 10))}
          {t.sla_due_at
            ? ` · target selesai ${tanggalWaktu(t.sla_due_at)}`
            : ""}
          {" · "}
          {t.message_count} pesan
        </p>
      </li>
    );
  }

  return (
    <div className="space-y-6">
      <Card title="Cari jawaban dulu di basis pengetahuan">
        <div className="flex flex-wrap gap-2">
          <input
            className={`${inputCls} flex-1`}
            value={kbQuery}
            onChange={(e) => setKbQuery(e.target.value)}
            placeholder="cth. cara mengajukan cuti, slip gaji, lupa kata sandi…"
            onKeyDown={(e) => {
              if (e.key === "Enter") void searchKb();
            }}
          />
          <button
            className={btnPrimary}
            disabled={searching}
            onClick={() => void searchKb()}
          >
            {searching ? "Mencari…" : "Cari"}
          </button>
        </div>
        {shownKb.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">
            {kbResults !== null
              ? "Tidak ada artikel yang cocok. Silakan buat tiket di bawah."
              : "Belum ada artikel. Coba kata kunci lain atau buat tiket."}
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {shownKb.map((a) => (
              <li key={a.id} className="flex items-start gap-2 py-2">
                <button
                  className="flex-1 text-left"
                  onClick={() => setOpenArticle(a)}
                >
                  <span className="text-sm font-medium text-slate-800 hover:underline">
                    📄 {a.title}
                  </span>
                  <span className="block text-xs text-slate-400">
                    {TICKET_CATEGORIES.find((c) => c.value === a.category)
                      ?.label ?? a.category}
                  </span>
                </button>
                {isHr && (
                  <button
                    className={btnDanger}
                    onClick={() => setDeletingKb(a)}
                  >
                    Hapus
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Buat tiket bantuan">
          <div className="grid gap-4">
            <Field label="Kategori">
              <select
                className={inputCls}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {TICKET_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Subjek">
              <input
                className={inputCls}
                value={subject}
                maxLength={200}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Ringkas masalah Anda"
              />
            </Field>
            <Field label="Deskripsi">
              <textarea
                className={inputCls}
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Jelaskan detailnya: sejak kapan, pesan error yang muncul, langkah yang sudah dicoba…"
              />
            </Field>
            <div>
              <button
                className={btnPrimary}
                disabled={saving}
                onClick={() => void createTicket()}
              >
                {saving ? "Mengirim…" : "Kirim tiket"}
              </button>
            </div>
          </div>
        </Card>

        <Card title={`Tiket saya (${myTickets.length})`}>
          {myTickets.length === 0 ? (
            <EmptyState message="Anda belum pernah membuat tiket." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {myTickets.map((t) => ticketRow(t, false))}
            </ul>
          )}
        </Card>
      </div>

      {isHr && (
        <>
          <Card title={`Semua tiket masuk (${allTickets.length})`}>
            {allTickets.length === 0 ? (
              <EmptyState message="Belum ada tiket dari karyawan." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {allTickets.map((t) => ticketRow(t, true))}
              </ul>
            )}
          </Card>

          <Card title="Tulis artikel basis pengetahuan">
            <div className="grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Kategori">
                  <select
                    className={inputCls}
                    value={kbCat}
                    onChange={(e) => setKbCat(e.target.value)}
                  >
                    {TICKET_CATEGORIES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Kata kunci pencarian (opsional)">
                  <input
                    className={inputCls}
                    value={kbKeywords}
                    maxLength={255}
                    onChange={(e) => setKbKeywords(e.target.value)}
                    placeholder="cth. gaji slip potongan"
                  />
                </Field>
              </div>
              <Field label="Judul artikel">
                <input
                  className={inputCls}
                  value={kbTitle}
                  maxLength={200}
                  onChange={(e) => setKbTitle(e.target.value)}
                  placeholder="cth. Cara mengunduh slip gaji"
                />
              </Field>
              <Field label="Isi artikel">
                <textarea
                  className={inputCls}
                  rows={5}
                  value={kbBody}
                  onChange={(e) => setKbBody(e.target.value)}
                  placeholder="Tulis langkah-langkahnya dengan jelas…"
                />
              </Field>
              <div>
                <button
                  className={btnPrimary}
                  disabled={savingKb}
                  onClick={() => void createKb()}
                >
                  {savingKb ? "Menyimpan…" : "Terbitkan artikel"}
                </button>
              </div>
            </div>
          </Card>
        </>
      )}

      {openArticle && (
        <Modal
          title={openArticle.title}
          onClose={() => setOpenArticle(null)}
          actions={
            <button
              className={btnSecondary}
              onClick={() => setOpenArticle(null)}
            >
              Tutup
            </button>
          }
        >
          <p className="whitespace-pre-wrap text-sm text-slate-700">
            {openArticle.body}
          </p>
          <p className="mt-3 text-xs text-slate-400">
            Belum terjawab? Buat tiket bantuan — tim HR akan menindaklanjuti.
          </p>
        </Modal>
      )}

      {detail && (
        <Modal
          title={detail.subject}
          onClose={() => setDetail(null)}
          actions={
            <button className={btnSecondary} onClick={() => setDetail(null)}>
              Tutup
            </button>
          }
        >
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              {TICKET_CATEGORIES.find((c) => c.value === detail.category)
                ?.label ?? detail.category}
              {detail.requester_name ? ` · dari ${detail.requester_name}` : ""}
              {" · dibuat "}
              {tanggalWaktu(detail.created_at)}
              {detail.sla_due_at
                ? ` · target selesai ${tanggalWaktu(detail.sla_due_at)}`
                : ""}
            </p>
            <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              {detail.description}
            </p>

            {isHr && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-slate-600">
                  Ubah status:
                </span>
                {(["diproses", "menunggu", "selesai", "ditutup"] as const).map(
                  (st) => (
                    <button
                      key={st}
                      className={
                        detail.status === st ? btnPrimary : btnSmall
                      }
                      disabled={detail.status === st}
                      onClick={() => void changeStatus(detail, st)}
                    >
                      {TICKET_STATUS[st].label}
                    </button>
                  )
                )}
              </div>
            )}

            <div className="max-h-64 space-y-2 overflow-y-auto">
              {messages.length === 0 ? (
                <p className="text-sm text-slate-400">
                  Belum ada balasan. Tulis pesan pertama di bawah.
                </p>
              ) : (
                messages.map((m) => (
                  <div key={m.id} className="rounded-lg bg-slate-50 p-3">
                    <p className="text-xs font-semibold text-slate-700">
                      {m.author_name}{" "}
                      <span className="font-normal text-slate-400">
                        · {tanggalWaktu(m.created_at)}
                      </span>
                    </p>
                    <p className="mt-0.5 whitespace-pre-wrap text-sm text-slate-700">
                      {m.body}
                    </p>
                  </div>
                ))
              )}
            </div>

            {detail.status !== "selesai" && detail.status !== "ditutup" ? (
              <div className="flex gap-2">
                <input
                  className={`${inputCls} flex-1`}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Tulis balasan…"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void sendReply();
                  }}
                />
                <button
                  className={btnPrimary}
                  disabled={sending || reply.trim() === ""}
                  onClick={() => void sendReply()}
                >
                  {sending ? "Mengirim…" : "Kirim"}
                </button>
              </div>
            ) : (
              <p className="text-xs text-emerald-700">
                Tiket ini sudah {detail.status}. Buat tiket baru bila masih
                butuh bantuan.
              </p>
            )}
          </div>
        </Modal>
      )}

      {deletingKb && (
        <Modal
          title="Hapus artikel?"
          onClose={() => setDeletingKb(null)}
          actions={
            <>
              <button
                className={btnSecondary}
                onClick={() => setDeletingKb(null)}
              >
                Batal
              </button>
              <button
                className={btnPrimary}
                onClick={() => void deleteKb(deletingKb)}
              >
                Ya, hapus
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            Artikel “{deletingKb.title}” akan dihapus dari basis pengetahuan.
          </p>
        </Modal>
      )}
    </div>
  );
}
