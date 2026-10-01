"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getApiBase, apiFetch, ApiError } from "@/lib/api";
import type { Offer, AcceptOfferResult } from "@/lib/types";
import { tanggal, tanggalWaktu, rupiah } from "@/lib/format";
import { Field, inputCls, btnPrimary, btnSecondary, btnDanger } from "@/components/ui";

const OFFER_STATUS_LABEL: Record<string, string> = {
  draft: "Draf",
  sent: "Terkirim",
  accepted: "Diterima",
  declined: "Ditolak",
  expired: "Kedaluwarsa",
};

export default function OfferAcceptPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [loading, setLoading] = useState(true);
  const [loggedIn, setLoggedIn] = useState(false);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Form terima
  const [nik, setNik] = useState("");
  const [fullName, setFullName] = useState("");
  const [birthPlace, setBirthPlace] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState("L");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [bankName, setBankName] = useState("");
  const [bankAccount, setBankAccount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<AcceptOfferResult | null>(null);

  // Tolak (mode login)
  const [declineNote, setDeclineNote] = useState("");
  const [declining, setDeclining] = useState(false);
  const [declinedMsg, setDeclinedMsg] = useState<string | null>(null);

  useEffect(() => {
    const hasToken = document.cookie
      .split(";")
      .some((c) => c.trim().startsWith("hris_token="));
    setLoggedIn(hasToken);
    if (hasToken) {
      apiFetch<Offer[]>("/recruitment/offers")
        .then((list) => {
          const found = list.find((o) => o.offer_token === token) ?? null;
          if (!found) setDetailError("Offer tidak ditemukan untuk token ini.");
          setOffer(found);
        })
        .catch(() => setDetailError("Gagal memuat detail offer."))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function accept() {
    if (!/^\d{16}$/.test(nik.trim())) {
      setFormError("NIK harus terdiri dari 16 digit angka.");
      return;
    }
    if (!fullName.trim()) {
      setFormError("Nama lengkap wajib diisi.");
      return;
    }
    if (!["L", "P"].includes(gender)) {
      setFormError("Jenis kelamin wajib dipilih.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const res = await fetch(
        `${getApiBase()}/public/offers/${encodeURIComponent(token)}/accept`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            nik: nik.trim(),
            full_name: fullName.trim(),
            birth_place: birthPlace.trim() || null,
            birth_date: birthDate || null,
            gender,
            email: email.trim() || null,
            phone: phone.trim() || null,
            bank_name: bankName.trim() || null,
            bank_account_no: bankAccount.trim() || null,
          }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : "Penawaran tidak valid atau sudah kedaluwarsa."
        );
      }
      setResult(await res.json());
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Gagal menerima tawaran.");
    } finally {
      setSubmitting(false);
    }
  }

  async function decline() {
    if (!offer) return;
    setDeclining(true);
    setDetailError(null);
    try {
      const updated = await apiFetch<Offer>(
        `/recruitment/offers/${offer.id}/decline`,
        {
          method: "POST",
          body: JSON.stringify({ note: declineNote.trim() || null }),
        }
      );
      setOffer(updated);
      setDeclinedMsg("Offer ditandai ditolak kandidat.");
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : "Gagal menolak offer.");
    } finally {
      setDeclining(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-2xl px-4 py-6">
          <h1 className="text-2xl font-bold text-slate-900">Tawaran Kerja</h1>
          <p className="text-sm text-slate-500">
            Konfirmasi penerimaan tawaran kerja Anda di bawah ini.
          </p>
        </div>
      </header>

      <div className="mx-auto max-w-2xl px-4 py-8">
        {loading && <p className="text-sm text-slate-500">Memuat…</p>}
        {detailError && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 ring-1 ring-red-200">
            {detailError}
          </div>
        )}

        {/* Mode login: tampilkan detail + tombol tolak */}
        {loggedIn && !loading && offer && (
          <div className="space-y-4">
            <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-4 text-lg font-semibold">Detail offer</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-500">Status</dt>
                  <dd className="font-medium">
                    {OFFER_STATUS_LABEL[offer.status] ?? offer.status}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Gaji</dt>
                  <dd className="font-medium">{rupiah(offer.salary)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Tanggal mulai</dt>
                  <dd className="font-medium">{tanggal(offer.start_date)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Tipe kontrak</dt>
                  <dd className="font-medium">{offer.contract_type}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Berlaku hingga</dt>
                  <dd className="font-medium">{tanggalWaktu(offer.expires_at)}</dd>
                </div>
              </dl>
            </div>
            {declinedMsg ? (
              <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200">
                {declinedMsg}
              </div>
            ) : (
              offer.status === "sent" && (
                <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
                  <h2 className="mb-3 text-lg font-semibold">Tandai offer ditolak</h2>
                  <Field label="Catatan">
                    <textarea
                      value={declineNote}
                      onChange={(e) => setDeclineNote(e.target.value)}
                      className={inputCls}
                      rows={3}
                      placeholder="mis. kandidat menerima tawaran lain"
                    />
                  </Field>
                  <button
                    className={`${btnDanger} mt-3`}
                    disabled={declining}
                    onClick={decline}
                  >
                    {declining ? "…" : "Tandai ditolak"}
                  </button>
                </div>
              )
            )}
            <Link href="/rekrutmen/lowongan" className={btnSecondary}>
              ← Ke modul Rekrutmen
            </Link>
          </div>
        )}

        {/* Mode anonim: form terima */}
        {!loggedIn && !loading && (
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            {result ? (
              <div className="text-center">
                <p className="text-4xl">✅</p>
                <h2 className="mt-3 text-lg font-semibold text-slate-900">
                  Tawaran diterima. Selamat bergabung!
                </h2>
                <p className="mt-2 text-sm text-slate-600">
                  Data kepegawaian Anda telah dibuat. Tim HR akan menghubungi Anda
                  mengenai langkah onboarding berikutnya.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">Form penerimaan tawaran</h2>
                <p className="text-sm text-slate-500">
                  Lengkapi data diri Anda untuk menerima tawaran kerja ini.
                </p>
                {formError && (
                  <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
                    {formError}
                  </div>
                )}
                <Field label="NIK (16 digit)" required>
                  <input
                    value={nik}
                    onChange={(e) => setNik(e.target.value.replace(/\D/g, "").slice(0, 16))}
                    className={inputCls}
                    inputMode="numeric"
                    maxLength={16}
                    placeholder="xxxxxxxxxxxxxxxx"
                  />
                </Field>
                <Field label="Nama lengkap" required>
                  <input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className={inputCls}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Tempat lahir">
                    <input
                      value={birthPlace}
                      onChange={(e) => setBirthPlace(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Tanggal lahir">
                    <input
                      type="date"
                      value={birthDate}
                      onChange={(e) => setBirthDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                </div>
                <Field label="Jenis kelamin" required>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className={inputCls}
                  >
                    <option value="L">Laki-laki</option>
                    <option value="P">Perempuan</option>
                  </select>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Email">
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Telepon">
                    <input
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Bank">
                    <input
                      value={bankName}
                      onChange={(e) => setBankName(e.target.value)}
                      className={inputCls}
                      placeholder="mis. BCA"
                    />
                  </Field>
                  <Field label="Nomor rekening">
                    <input
                      value={bankAccount}
                      onChange={(e) => setBankAccount(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                </div>
                <button className={btnPrimary} disabled={submitting} onClick={accept}>
                  {submitting ? "Mengirim…" : "Saya terima tawaran ini"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
