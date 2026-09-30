# ADR-0011: Klaim & Pinjaman Karyawan (Sprint 8)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §24.2 baris S8, §11.5 (BEN-001/BEN-003). Demo goal PRD:
"Pengajuan klaim kesehatan sampai reimbursement tercatat."

## Keputusan

1. **Klaim — approval 2 level (pola cuti Sprint 5)**:
   `draft → submitted → approved_l1 (atasan langsung via is_manager_of) →
   approved (HR/Finance, izin correct) → paid`.
   Tolak/cancel membebaskan plafon. Self-approval L1 & final ditolak 422.
2. **Plafon dua lapis per jenis klaim** (`ClaimType`): `limit_per_claim`
   (ditolak 422 saat create/submit) dan `limit_per_year` (terpakai =
   status submitted/approved_l1/approved/paid; ditolak 422 bila terlampaui).
   `requires_receipt=True` menolak submit tanpa `receipt_document_id`.
3. **Reimbursement = earning NON-PAJAK di payroll**: masuk `breakdown`
   (`reimbursement`) dan kolom `PayrollLine.reimbursement_amount`;
   semua perhitungan PPh 21 & basis pensiun memakai
   `taxable_gross = base_gross − reimbursement`. THR memakai basis gaji
   tetap (tidak terpengaruh reimbursement). `paid_via="transfer"` =
   dibayar terpisah, tidak masuk run.
4. **Pinjaman — 1 aktif per karyawan** (default `allow_multiple_active=False`):
   `draft → submitted → active → completed`. Batas approve: nominal ≤
   `max_amount_multiplier × gaji bulanan` (gaji_pokok+tunjangan_tetap dari
   CompInfo kini; default 3×), tenor ≤ `max_tenor_months` (default 24).
5. **Bunga flat tahunan sederhana** (default 0%):
   `total = pokok + round(pokok × rate × tenor/12)`;
   `monthly_installment = total // tenor`. Tanpa denda, tanpa bunga
   menurun. Angka dibulatkan ke rupiah.
6. **Cicilan lazy per periode**: `LoanInstallment` dibuat saat payroll run
   (idempoten per (loan_id, period) via UniqueConstraint). Masuk run
   sebagai deduction `cicilan_pinjaman`. `lock_run` menandai angsuran
   `paid`, mengurangi `remaining_total`, dan menyelesaikan pinjaman yang
   lunas (`completed`).
7. **Payoff (pelunasan dipercepat)**: membuat angsuran `kind="payoff"`
   sebesar sisa total di periode terbuka berikutnya; dipotong penuh di
   run itu.
8. **RLS**: 5 tabel baru (`claim_types`, `claims`, `tenant_loan_policies`,
   `loans`, `loan_installments`) didaftarkan manual di whitelist
   `migrations/001_rls.sql` (pelajaran Sprint 7).
9. **Grant RBP seed**: HR Admin penuh; Manajer = claim view+correct
   (L1 timnya), loan/loan_policy view; Karyawan = ESS claim & loan
   (view+insert+correct milik sendiri), claim_type/loan_policy view.
   Persetujuan pinjaman & approval final klaim khusus HR/Finance.

## Simplifikasi vs PRD (jujur)

- **Tanpa OCR struk** (BEN-001): struk = dokumen upload biasa (ID dokumen
  di `receipt_document_id`, tanpa FK keras).
- **Tanpa e-sign & tanpa payroll bank-file khusus reimbursement**;
  reimbursement tercatat sebagai komponen slip, bukan file transfer
  tersendiri.
- **Tanpa EWA / Earned Wage Access** (BEN-004) dan tanpa cash advance
  settlement (BEN-002): cakupan Sprint 8 = klaim + pinjaman kasbon saja.
- **Tanpa denda keterlambatan & tanpa bunga menurun**; payoff tanpa
  penalti. Karyawan tidak bisa self-approve; tanpa workflow delegasi
  approval bila atasan cuti.
- Run yang dikunci dengan cicilan > take-home ditolak (guard take-home
  negatif Sprint 4) — pinjaman besar harus dilunasi manual/transfer.

## Konsekuensi

- `evaluate_employment` mendapat 4 parameter opsional baru
  (`reimbursement`, `reimbursement_claim_ids`, `loan_installment`,
  `loan_installment_ids`); kontrak API lama tetap kompatibel.
- `_jsonable` di `services/audit.py` kini menangani `Decimal` (kebijakan
  pinjaman memakai kolom Numeric).
