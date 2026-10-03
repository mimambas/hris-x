"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { tanggalWaktu } from "@/lib/format";
import { useAuth } from "@/components/AuthContext";
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

interface Profile {
  person_id: string;
  employment_id: string | null;
  full_name: string;
  nik: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  bank_name: string | null;
  bank_account_no: string | null;
  ptkp: string;
}

interface DataChange {
  id: string;
  employment_id: string;
  person_id: string;
  person_name: string | null;
  change_type: string;
  old_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  status: string;
  note: string | null;
  otp_verified_at: string | null;
  otp_expires_at: string | null;
  decision_reason: string | null;
  decided_at: string | null;
  applied_at: string | null;
  created_at: string;
}

const TYPE_META: Record<string, { label: string; icon: string }> = {
  alamat: { label: "Alamat domisili", icon: "🏠" },
  telepon: { label: "Nomor telepon", icon: "📱" },
  email: { label: "Email pribadi", icon: "✉️" },
  rekening: { label: "Rekening bank", icon: "🏦" },
  tanggungan: { label: "Tanggungan (PTKP)", icon: "👨‍👩‍👧" },
};

const STATUS_META: Record<string, { label: string; cls: string }> = {
  menunggu_otp: { label: "Menunggu verifikasi OTP", cls: "bg-violet-100 text-violet-800" },
  menunggu_persetujuan: { label: "Menunggu persetujuan HR", cls: "bg-amber-100 text-amber-800" },
  disetujui: { label: "Disetujui & diterapkan", cls: "bg-emerald-100 text-emerald-800" },
  ditolak: { label: "Ditolak", cls: "bg-rose-100 text-rose-700" },
  dibatalkan: { label: "Dibatalkan", cls: "bg-slate-200 text-slate-600" },
};

const PTKP_OPTIONS = ["TK/0", "TK/1", "TK/2", "TK/3", "K/0", "K/1", "K/2", "K/3"];

function describe(c: DataChange): string {
  const nv = c.new_values;
  switch (c.change_type) {
    case "alamat":
      return String(nv.address ?? "");
    case "telepon":
      return String(nv.phone ?? "");
    case "email":
      return String(nv.email ?? "");
    case "rekening":
      return `${String(nv.bank_name ?? "")} ${String(nv.bank_account_no ?? "")}`;
    case "tanggungan":
      return `PTKP ${String(nv.ptkp ?? "")}`;
    default:
      return "";
  }
}

function maskAccount(no: string | null): string {
  if (!no) return "—";
  if (no.length <= 4) return no;
  return `••••${no.slice(-4)}`;
}

export default function ProfilPage() {
  const { user } = useAuth();
  const isHr = Boolean(user?.is_hr || user?.is_superadmin);

  const [profile, setProfile] = useState<Profile | null>(null);
  const [mine, setMine] = useState<DataChange[]>([]);
  const [queue, setQueue] = useState<DataChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Form ajukan.
  const [changeType, setChangeType] = useState("alamat");
  const [fAddress, setFAddress] = useState("");
  const [fPhone, setFPhone] = useState("");
  const [fEmail, setFEmail] = useState("");
  const [fBank, setFBank] = useState("");
  const [fAccount, setFAccount] = useState("");
  const [fPtkp, setFPtkp] = useState("TK/0");
  const [fNote, setFNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // OTP & keputusan.
  const [otpCode, setOtpCode] = useState<Record<string, string>>({});
  const [otpBusy, setOtpBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<DataChange | null>(null);
  const [approving, setApproving] = useState<DataChange | null>(null);
  const [rejecting, setRejecting] = useState<DataChange | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [otpPeek, setOtpPeek] = useState<{ c: DataChange; code: string } | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [me, mineRows] = await Promise.all([
        apiFetch<Profile>("/data-changes/me").catch(() => null),
        apiFetch<DataChange[]>("/data-changes/mine").catch(() => []),
      ]);
      setProfile(me);
      setMine(mineRows);
      if (isHr) {
        const q = await apiFetch<DataChange[]>("/data-changes").catch(
          () => []
        );
        setQueue(q);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Gagal memuat profil.");
    } finally {
      setLoading(false);
    }
  }, [isHr]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!profile) return;
    setFAddress(profile.address ?? "");
    setFPhone(profile.phone ?? "");
    setFEmail(profile.email ?? "");
    setFBank(profile.bank_name ?? "");
    setFAccount(profile.bank_account_no ?? "");
    setFPtkp(profile.ptkp);
  }, [profile]);

  function newValues(): Record<string, unknown> {
    switch (changeType) {
      case "alamat":
        return { address: fAddress.trim() };
      case "telepon":
        return { phone: fPhone.trim() };
      case "email":
        return { email: fEmail.trim() };
      case "rekening":
        return { bank_name: fBank.trim(), bank_account_no: fAccount.trim() };
      default:
        return { ptkp: fPtkp };
    }
  }

  async function submit() {
    setSubmitting(true);
    setActionError(null);
    try {
      await apiFetch("/data-changes", {
        method: "POST",
        body: JSON.stringify({
          change_type: changeType,
          new_values: newValues(),
          note: fNote.trim() || null,
        }),
      });
      setNotice(
        changeType === "rekening"
          ? "Permintaan dibuat. Minta kode OTP ke HR, lalu verifikasi pada daftar permintaan Anda di bawah."
          : "Permintaan terkirim. Menunggu persetujuan HR."
      );
      setFNote("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal mengajukan.");
    } finally {
      setSubmitting(false);
    }
  }

  async function verifyOtp(c: DataChange) {
    const code = (otpCode[c.id] ?? "").trim();
    if (!/^\d{6}$/.test(code)) {
      setActionError("Kode OTP harus 6 angka.");
      return;
    }
    setOtpBusy(c.id);
    setActionError(null);
    try {
      await apiFetch(`/data-changes/${c.id}/verify-otp`, {
        method: "POST",
        body: JSON.stringify({ code }),
      });
      setNotice("OTP terverifikasi. Permintaan diteruskan ke persetujuan HR.");
      await load();
    } catch (e) {
      setActionError(
        e instanceof ApiError
          ? e.message === "OTP_SALAH"
            ? "Kode OTP salah. Periksa kembali kode dari HR."
            : e.message === "OTP_KEDALUWARSA"
              ? "Kode OTP kedaluwarsa. Minta kode baru ke HR atau kirim ulang."
              : e.message
          : "Verifikasi gagal."
      );
    } finally {
      setOtpBusy(null);
    }
  }

  async function resendOtp(c: DataChange) {
    setOtpBusy(c.id);
    try {
      await apiFetch(`/data-changes/${c.id}/resend-otp`, { method: "POST" });
      setNotice("Kode OTP baru dibuat. Minta kodenya ke HR.");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal kirim ulang.");
    } finally {
      setOtpBusy(null);
    }
  }

  async function cancel(c: DataChange) {
    try {
      await apiFetch(`/data-changes/${c.id}/cancel`, { method: "POST" });
      setNotice("Permintaan dibatalkan.");
      setCancelling(null);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal membatalkan.");
    }
  }

  async function approve(c: DataChange) {
    try {
      await apiFetch(`/data-changes/${c.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ reason: null }),
      });
      setNotice(`Perubahan ${TYPE_META[c.change_type]?.label ?? ""} ${c.person_name ?? ""} disetujui dan diterapkan.`);
      setApproving(null);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menyetujui.");
    }
  }

  async function reject(c: DataChange) {
    if (!rejectReason.trim()) {
      setActionError("Alasan penolakan wajib diisi.");
      return;
    }
    try {
      await apiFetch(`/data-changes/${c.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason.trim() }),
      });
      setNotice("Permintaan ditolak.");
      setRejecting(null);
      setRejectReason("");
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Gagal menolak.");
    }
  }

  async function peekOtp(c: DataChange) {
    try {
      const r = await apiFetch<{ code: string }>(`/data-changes/${c.id}/otp`);
      setOtpPeek({ c, code: r.code });
    } catch (e) {
      setActionError(
        e instanceof ApiError
          ? "Kode OTP tidak tersedia (sudah dipakai atau kedaluwarsa). Minta karyawan kirim ulang kode."
          : "Gagal membaca kode."
      );
    }
  }

  function changeRow(c: DataChange, hrView: boolean) {
    const st = STATUS_META[c.status] ?? STATUS_META.menunggu_persetujuan;
    const meta = TYPE_META[c.change_type];
    return (
      <li key={c.id} className="py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span aria-hidden>{meta?.icon}</span>
          <p className="flex-1 text-sm font-medium text-slate-800">
            {meta?.label ?? c.change_type}
            {hrView && c.person_name ? ` — ${c.person_name}` : ""}
          </p>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}>
            {st.label}
          </span>
        </div>
        <p className="mt-0.5 text-sm text-slate-600">
          Nilai baru: <strong>{describe(c)}</strong>
        </p>
        <p className="text-xs text-slate-400">
          Diajukan {tanggalWaktu(c.created_at)}
          {c.note ? ` · ${c.note}` : ""}
          {c.otp_verified_at ? " · OTP terverifikasi ✓" : ""}
          {c.status === "ditolak" && c.decision_reason
            ? ` · Alasan: ${c.decision_reason}`
            : ""}
        </p>

        {!hrView && c.status === "menunggu_otp" && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              className={`${inputCls} w-36`}
              inputMode="numeric"
              maxLength={6}
              placeholder="Kode OTP 6 angka"
              value={otpCode[c.id] ?? ""}
              onChange={(e) =>
                setOtpCode((prev) => ({
                  ...prev,
                  [c.id]: e.target.value.replace(/\D/g, ""),
                }))
              }
            />
            <button
              className={btnPrimary}
              disabled={otpBusy === c.id}
              onClick={() => void verifyOtp(c)}
            >
              Verifikasi OTP
            </button>
            <button
              className={btnSmall}
              disabled={otpBusy === c.id}
              onClick={() => void resendOtp(c)}
            >
              Kirim ulang kode
            </button>
          </div>
        )}

        {!hrView &&
          (c.status === "menunggu_otp" ||
            c.status === "menunggu_persetujuan") && (
            <button
              className={`${btnSmall} mt-2`}
              onClick={() => setCancelling(c)}
            >
              Batalkan permintaan
            </button>
          )}

        {hrView && c.status === "menunggu_otp" && (
          <div className="mt-2">
            <button className={btnSmall} onClick={() => void peekOtp(c)}>
              Lihat kode OTP untuk diteruskan
            </button>
          </div>
        )}
        {hrView && c.status === "menunggu_persetujuan" && (
          <div className="mt-2 flex flex-wrap gap-2">
            <button className={btnPrimary} onClick={() => setApproving(c)}>
              Setujui & terapkan
            </button>
            <button
              className={btnSecondary}
              onClick={() => {
                setRejectReason("");
                setRejecting(c);
              }}
            >
              Tolak
            </button>
          </div>
        )}
      </li>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profil & Data Saya"
        subtitle="Perubahan data pribadi berlaku setelah disetujui HR. Perubahan rekening bank wajib verifikasi OTP."
      />

      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      )}
      {actionError && <ErrorBox message={actionError} />}

      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <>
          {!profile && !isHr && (
            <EmptyState message="Akun Anda tidak terikat data karyawan, jadi halaman ini tidak tersedia." />
          )}
          {profile && (
          <>
          <Card title="Data saya saat ini">
            <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <dt className="text-xs text-slate-400">Nama</dt>
                <dd className="font-medium text-slate-800">{profile.full_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">NIK</dt>
                <dd className="font-mono text-xs text-slate-700">{profile.nik}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Tanggungan (PTKP)</dt>
                <dd className="font-medium text-slate-800">{profile.ptkp}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Alamat domisili</dt>
                <dd className="text-slate-700">{profile.address ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Telepon</dt>
                <dd className="text-slate-700">{profile.phone ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Email pribadi</dt>
                <dd className="text-slate-700">{profile.email ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Rekening gaji</dt>
                <dd className="text-slate-700">
                  {profile.bank_name ?? "—"}{" "}
                  {maskAccount(profile.bank_account_no)}
                </dd>
              </div>
            </dl>
          </Card>

          <Card title="Ajukan perubahan data">
            <div className="grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Jenis perubahan">
                  <select
                    className={inputCls}
                    value={changeType}
                    onChange={(e) => setChangeType(e.target.value)}
                  >
                    {Object.entries(TYPE_META).map(([v, m]) => (
                      <option key={v} value={v}>
                        {m.icon} {m.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Catatan (opsional)">
                  <input
                    className={inputCls}
                    maxLength={500}
                    value={fNote}
                    onChange={(e) => setFNote(e.target.value)}
                    placeholder="cth. Pindah domisili per Oktober"
                  />
                </Field>
              </div>

              {changeType === "alamat" && (
                <Field label="Alamat domisili baru">
                  <textarea
                    className={inputCls}
                    rows={3}
                    value={fAddress}
                    onChange={(e) => setFAddress(e.target.value)}
                    placeholder="Jalan, nomor, RT/RW, kelurahan, kecamatan, kota, kode pos"
                  />
                </Field>
              )}
              {changeType === "telepon" && (
                <Field label="Nomor telepon baru">
                  <input
                    className={inputCls}
                    value={fPhone}
                    maxLength={30}
                    onChange={(e) => setFPhone(e.target.value)}
                    placeholder="08xxxxxxxxxx"
                  />
                </Field>
              )}
              {changeType === "email" && (
                <Field label="Email pribadi baru">
                  <input
                    className={inputCls}
                    type="email"
                    value={fEmail}
                    onChange={(e) => setFEmail(e.target.value)}
                    placeholder="nama@email.com"
                  />
                </Field>
              )}
              {changeType === "rekening" && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Bank baru">
                    <input
                      className={inputCls}
                      value={fBank}
                      maxLength={100}
                      onChange={(e) => setFBank(e.target.value)}
                      placeholder="cth. Mandiri"
                    />
                  </Field>
                  <Field label="Nomor rekening baru">
                    <input
                      className={inputCls}
                      inputMode="numeric"
                      value={fAccount}
                      maxLength={32}
                      onChange={(e) =>
                        setFAccount(e.target.value.replace(/\D/g, ""))
                      }
                      placeholder="Hanya angka"
                    />
                  </Field>
                  <p className="text-xs text-amber-700 sm:col-span-2">
                    🔐 Perubahan rekening wajib verifikasi OTP: setelah
                    mengajukan, minta kode OTP ke HR lalu verifikasi di
                    daftar permintaan di bawah.
                  </p>
                </div>
              )}
              {changeType === "tanggungan" && (
                <Field label="Status tanggungan (PTKP) baru">
                  <select
                    className={inputCls}
                    value={fPtkp}
                    onChange={(e) => setFPtkp(e.target.value)}
                  >
                    {PTKP_OPTIONS.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </Field>
              )}

              <div>
                <button
                  className={btnPrimary}
                  disabled={submitting}
                  onClick={() => void submit()}
                >
                  {submitting ? "Mengirim…" : "Kirim permintaan"}
                </button>
              </div>
            </div>
          </Card>

          <Card title={`Permintaan saya (${mine.length})`}>
            {mine.length === 0 ? (
              <EmptyState message="Belum ada permintaan perubahan data." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {mine.map((c) => changeRow(c, false))}
              </ul>
            )}
          </Card>
          </>)}

          {isHr && (
            <Card title={`Antrean persetujuan perubahan data (${queue.filter((q) => q.status === "menunggu_otp" || q.status === "menunggu_persetujuan").length} menunggu)`}>
              {queue.length === 0 ? (
                <EmptyState message="Belum ada permintaan perubahan data dari karyawan." />
              ) : (
                <ul className="divide-y divide-slate-100">
                  {queue.map((c) => changeRow(c, true))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}

      {cancelling && (
        <Modal
          title="Batalkan permintaan?"
          onClose={() => setCancelling(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setCancelling(null)}>
                Kembali
              </button>
              <button className={btnPrimary} onClick={() => void cancel(cancelling)}>
                Ya, batalkan
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            Permintaan {TYPE_META[cancelling.change_type]?.label} (
            {describe(cancelling)}) akan dibatalkan.
          </p>
        </Modal>
      )}

      {approving && (
        <Modal
          title="Setujui & terapkan perubahan?"
          onClose={() => setApproving(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setApproving(null)}>
                Batal
              </button>
              <button className={btnPrimary} onClick={() => void approve(approving)}>
                Ya, setujui
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">
            {TYPE_META[approving.change_type]?.label} untuk{" "}
            {approving.person_name ?? "karyawan"} menjadi:{" "}
            <strong>{describe(approving)}</strong>. Data lama langsung
            digantikan dan tercatat di audit.
          </p>
        </Modal>
      )}

      {rejecting && (
        <Modal
          title="Tolak permintaan?"
          onClose={() => setRejecting(null)}
          actions={
            <>
              <button className={btnSecondary} onClick={() => setRejecting(null)}>
                Batal
              </button>
              <button
                className={btnPrimary}
                disabled={!rejectReason.trim()}
                onClick={() => void reject(rejecting)}
              >
                Ya, tolak
              </button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              {TYPE_META[rejecting.change_type]?.label} —{" "}
              {rejecting.person_name ?? ""}: {describe(rejecting)}
            </p>
            <Field label="Alasan penolakan (wajib)">
              <input
                className={inputCls}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Alasan untuk karyawan"
              />
            </Field>
          </div>
        </Modal>
      )}

      {otpPeek && (
        <Modal
          title="Kode OTP karyawan"
          onClose={() => setOtpPeek(null)}
          actions={
            <button className={btnSecondary} onClick={() => setOtpPeek(null)}>
              Tutup
            </button>
          }
        >
          <p className="text-sm text-slate-600">
            Teruskan kode ini ke {otpPeek.c.person_name ?? "karyawan"} lewat
            kanal internal perusahaan. Kode berlaku 10 menit.
          </p>
          <p className="mt-3 text-center font-mono text-3xl font-bold tracking-[0.3em] text-slate-900">
            {otpPeek.code}
          </p>
        </Modal>
      )}
    </div>
  );
}
