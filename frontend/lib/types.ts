// Tipe data sesuai skema backend HRIS-X (app/schemas/schemas.py).

export interface LoginResponse {
  access_token: string;
  token_type: string;
  tenant_id: string;
  user_id: string;
  roles: string[];
}

export interface Me {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  is_superadmin: boolean;
  roles: string[];
  person_id: string | null;
  is_hr: boolean; // boleh approve final (L2 cuti/lembur, final klaim, approve pinjaman)
}

export interface Person {
  id: string;
  nik: string;
  full_name: string;
  birth_place: string | null;
  birth_date: string | null;
  gender: string | null; // "L" | "P"
  email: string | null;
  phone: string | null;
  npwp: string | null;
  ptkp: string;
  bpjs_kes_no: string | null;
  bpjs_tk_no: string | null;
  bank_name: string | null;
  bank_account_no: string | null;
}

export interface Employment {
  id: string;
  person_id: string;
  legal_entity_id: string;
  start_date: string;
  end_date: string | null;
  status: string;
}

export interface JobInfo {
  id: string;
  employment_id: string;
  valid_from: string;
  valid_to: string;
  seq_no: number;
  job_id: string;
  org_unit_id: string;
  location_id: string;
  manager_employment_id: string | null;
  event: string;
  event_reason: string;
}

export interface ContractVersion {
  id: string;
  contract_id: string;
  contract_type: string;
  contract_number: string;
  valid_from: string;
  valid_to: string;
  seq_no: number;
  event: string;
  event_reason: string;
}

export interface Contract {
  id: string;
  employment_id: string;
  current_version: ContractVersion | null;
  versions: ContractVersion[];
}

export interface Document {
  id: string;
  person_id: string | null;
  employment_id: string | null;
  doc_type: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  is_current: boolean;
  notes: string | null;
}

export interface LeaveType {
  id: string;
  code: string;
  name: string;
  quota_days: number;
  accrual: string;
  min_service_months: number;
  requires_doc: boolean;
  deducts_balance: boolean;
  is_active: boolean;
}

export type LeaveStatus =
  | "draft"
  | "submitted"
  | "approved_l1"
  | "approved"
  | "rejected"
  | "cancelled";

export interface LeaveRequest {
  id: string;
  employment_id: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  days: number;
  reason: string | null;
  status: LeaveStatus;
  l1_approved_at: string | null;
  l2_approved_at: string | null;
  rejection_reason: string | null;
}

export interface LeaveBalance {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_code: string;
  year: number;
  entitled: number;
  used: number;
  remaining: number;
}

export interface HeadcountResponse {
  as_of: string;
  total: number;
  by_org_unit: Record<string, number>;
  by_contract_type: Record<string, number>;
  by_gender: Record<string, number>;
  by_status: Record<string, number>;
  new_this_month: number;
  left_this_month: number;
}

export interface TurnoverMonth {
  period: string;
  terminated: number;
  avg_headcount: number;
  rate_pct: number;
}

export interface TurnoverResponse {
  period: string;
  terminated: number;
  headcount_start: number;
  headcount_end: number;
  avg_headcount: number;
  rate_pct: number;
  by_org_unit: Record<string, number>;
  trend_12_months: TurnoverMonth[];
}

export interface PayrollRun {
  id: string;
  period: string;
  status: string;
  pph21_method: string;
  include_thr: boolean;
  totals: Record<string, number>;
  headcount: number;
  created_at: string;
  locked_at: string | null;
}

export interface PayJournalEntry {
  cost_center_code: string;
  cost_center_name: string;
  account_code: string;
  account_name: string;
  debit: number;
  credit: number;
}

export interface PayJournalCostCenter {
  cost_center_code: string;
  cost_center_name: string;
  total_debit: number;
  total_credit: number;
  balanced: boolean;
}

export interface PayJournal {
  run_id: string;
  period: string;
  status: string;
  journal_date: string;
  entries: PayJournalEntry[];
  per_cost_center: PayJournalCostCenter[];
  total_debit: number;
  total_credit: number;
  balanced: boolean;
}

export interface PayrollLine {
  id: string;
  employment_id: string;
  person_name: string;
  nik: string;
  ptkp: string;
  breakdown: Record<string, unknown>;
  gross: number;
  total_deductions: number;
  pph21: number;
  pph21_borne_by: string;
  thr_amount: number;
  retro_amount: number;
  reimbursement_amount: number;
  take_home_pay: number;
}

export interface OrgChartLegalEntity {
  id: string;
  name: string;
}

export interface OrgChartNode {
  id: string;
  name: string;
  legal_entity: OrgChartLegalEntity;
  children: OrgChartNode[];
}

export interface AttendanceRecord {
  id: string;
  employment_id: string;
  date: string;
  version: number;
  check_in: string | null;
  check_out: string | null;
  source: string;
  status: string; // "present" | "late" | "absent" | ...
  late_minutes: number;
  early_leave_minutes: number;
  work_minutes: number;
  correction_reason: string | null;
}

export interface AttendanceSummary {
  period: string;
  employment_id: string;
  present: number;
  late: number;
  absent: number;
  leave: number;
  holiday: number;
  total_work_minutes: number;
  total_late_minutes: number;
}

// ---------------------------------------------------------------- Rekrutmen (Sprint 6)

export interface OrgUnit {
  id: string;
  legal_entity_id: string;
  parent_id: string | null;
  name: string;
}

export interface Job {
  id: string;
  code: string;
  title: string;
}

export interface Location {
  id: string;
  name: string;
  timezone: string;
}

export interface LegalEntity {
  id: string;
  name: string;
  npwp: string | null;
}

export interface Requisition {
  id: string;
  org_unit_id: string;
  job_title: string;
  headcount: number;
  reason: string | null;
  status: string; // "draft" | "submitted" | "approved" | "rejected"
}

export interface JobPosting {
  id: string;
  requisition_id: string;
  title: string;
  description: string | null;
  requirements: string | null;
  employment_type: string;
  location: string | null;
  status: string; // "draft" | "published" | "closed"
  published_at: string | null;
  closed_at: string | null;
}

export interface PublicJob {
  id: string;
  title: string;
  description: string | null;
  requirements: string | null;
  employment_type: string;
  location: string | null;
  published_at: string | null;
}

export interface Candidate {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  cv_file_path: string | null;
  source: string;
}

export interface JobApplication {
  id: string;
  posting_id: string;
  candidate_id: string;
  status: string; // applied|screening|interview|offering|hired|rejected|withdrawn
  applied_at: string;
}

export interface Interview {
  id: string;
  application_id: string;
  scheduled_at: string;
  interviewer_ids: string[];
  location: string | null;
  mode: string; // "onsite" | "online"
  status: string; // "scheduled" | "completed" | "cancelled"
}

export interface InterviewFeedback {
  id: string;
  interview_id: string;
  interviewer_id: string;
  score: number;
  notes: string | null;
  recommendation: string; // "hire" | "no_hire" | "consider"
}

export interface Offer {
  id: string;
  application_id: string;
  salary: number;
  start_date: string;
  contract_type: string;
  expires_at: string;
  status: string; // "draft" | "sent" | "accepted" | "declined" | "expired"
  offer_token: string | null;
}

export interface AcceptOfferResult {
  person_id: string;
  employment_id: string;
  job_info_id: string;
  nik: string;
  full_name: string;
  start_date: string;
}

// ---------------------------------------------------------------- Klaim (Sprint 8)
export interface ClaimType {
  id: string;
  code: string;
  name: string;
  limit_per_year: number | null;
  limit_per_claim: number | null;
  requires_receipt: boolean;
  active: boolean;
}

export type ClaimStatus =
  | "draft"
  | "submitted"
  | "approved_l1"
  | "approved"
  | "rejected"
  | "cancelled"
  | "paid";

export interface Claim {
  id: string;
  employment_id: string;
  claim_type_id: string;
  amount: number;
  claim_date: string;
  description: string | null;
  receipt_document_id: string | null;
  status: ClaimStatus;
  paid_via: string; // "payroll" | "transfer"
  payroll_run_id: string | null;
  submitted_at: string | null;
  approved_at: string | null;
  paid_at: string | null;
  payment_ref: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface ClaimSummary {
  claim_type_id: string;
  claim_type_code: string;
  claim_type_name: string;
  limit_per_year: number | null;
  used: number;
  remaining: number | null;
}

// ---------------------------------------------------------------- Pinjaman (Sprint 8)
export interface LoanPolicy {
  id: string;
  max_amount_multiplier: number;
  max_tenor_months: number;
  default_interest_rate: number;
  allow_multiple_active: boolean;
}

export type LoanStatus =
  | "draft"
  | "submitted"
  | "active"
  | "rejected"
  | "cancelled"
  | "completed";

export interface Loan {
  id: string;
  employment_id: string;
  principal_amount: number;
  interest_rate: number;
  total_payable: number;
  tenor_months: number;
  monthly_installment: number;
  remaining_total: number;
  purpose: string | null;
  status: LoanStatus;
  submitted_at: string | null;
  approved_at: string | null;
  paid_off_at: string | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface LoanInstallment {
  id: string;
  loan_id: string;
  period: string;
  amount: number;
  kind: string; // "regular" | "payoff"
  status: string; // "pending" | "paid"
  payroll_run_id: string | null;
  paid_at: string | null;
}

export interface Document {
  id: string;
  person_id: string | null;
  employment_id: string | null;
  doc_type: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  is_current: boolean;
  notes: string | null;
}

// ------------------------------------------------------------------ Lembur
export interface OvertimeRequest {
  id: string;
  employment_id: string;
  date: string;
  start_time: string | null;
  end_time: string | null;
  hours: number;
  reason: string | null;
  status: string;
  pay_amount: number;
  rejection_reason: string | null;
}

export interface OvertimeRate {
  first_hour_mult: number;
  next_hour_mult: number;
  divisor: number;
}

export interface OnboardingTemplate {
  id: string;
  name: string;
  kind: "onboarding" | "offboarding";
  is_active: boolean;
  task_count: number;
  created_at: string;
}

export interface OnboardingTemplateTask {
  id: string;
  template_id: string;
  title: string;
  team: string;
  due_offset_days: number;
  sort_order: number;
  required_doc_type: string | null;
}

export interface OnboardingTemplateDetail {
  template: OnboardingTemplate;
  tasks: OnboardingTemplateTask[];
}

export interface OnboardingProcess {
  id: string;
  person_id: string;
  person_name: string | null;
  employment_id: string | null;
  template_id: string;
  template_name: string | null;
  kind: "onboarding" | "offboarding";
  status: "in_progress" | "completed" | "cancelled";
  start_date: string;
  target_date: string | null;
  notes: string | null;
  total_tasks: number;
  done_tasks: number;
  overdue_tasks: number;
  created_at: string;
  completed_at: string | null;
}

export interface OnboardingTask {
  id: string;
  process_id: string;
  title: string;
  team: string;
  assignee_user_id: string | null;
  assignee_name: string | null;
  due_date: string;
  status: "pending" | "in_progress" | "done" | "skipped";
  is_overdue: boolean;
  completed_at: string | null;
  notes: string | null;
  required_doc_type?: string | null;
  doc_ready?: boolean | null;
}

export interface OnboardingUserOption {
  id: string;
  full_name: string;
  email: string;
}

// ---------------------------------------------------------------------------
// Kompensasi (CMP, PRD 12.4)
// ---------------------------------------------------------------------------

export interface PayGrade {
  id: string;
  code: string;
  name: string;
  band_min: number;
  band_mid: number;
  band_max: number;
  is_active: boolean;
  created_at: string;
}

export interface JobGrade {
  job_id: string;
  code: string;
  title: string;
  pay_grade_id: string | null;
  grade_code: string | null;
  grade_name: string | null;
}

export interface CompEmployee {
  person_id: string;
  employment_id: string;
  person_name: string | null;
  org_unit_id: string | null;
  org_unit_name: string | null;
  job_id: string | null;
  job_title: string | null;
  grade_id: string | null;
  grade_code: string | null;
  grade_name: string | null;
  gaji_pokok: number | null;
  compa_ratio: number | null;
}

export interface CompCycle {
  id: string;
  name: string;
  kind: string;
  period_year: number;
  effective_date: string;
  status: string;
  guideline: { min_rating: number; max_rating: number; min_pct: number; max_pct: number }[] | null;
  created_at: string;
  finalized_at: string | null;
  proposal_total: number;
  proposal_approved: number;
}

export interface CompBudget {
  org_unit_id: string;
  org_unit_name: string | null;
  budget_amount: number | null;
  used_amount: number;
  remaining: number | null;
}

export interface CompProposal {
  id: string;
  cycle_id: string;
  employment_id: string;
  person_id: string;
  person_name: string | null;
  org_unit_id: string | null;
  org_unit_name: string | null;
  current_salary: number;
  proposed_salary: number;
  increase_pct: number;
  annualized_increase: number;
  rating: number | null;
  guideline_min_pct: number | null;
  guideline_max_pct: number | null;
  within_guideline: boolean | null;
  status: string;
  over_budget: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompCycleDetail {
  cycle: CompCycle;
  budgets: CompBudget[];
  proposals: CompProposal[];
}

export interface TotalRewards {
  person_id: string;
  person_name: string | null;
  as_of: string;
  monthly_components: Record<string, number>;
  monthly_cash: number;
  employer_bpjs_monthly: Record<string, number>;
  employer_bpjs_total_monthly: number;
  thr_estimate: number;
  annual_total: number;
}

export interface PayEquityRow {
  grade_code: string | null;
  grade_name: string | null;
  gender: string;
  headcount: number;
  avg_salary: number | null;
  median_salary: number | null;
  suppressed: boolean;
}

export interface PayEquity {
  rows: PayEquityRow[];
  gaps: {
    grade_code: string | null;
    grade_name: string | null;
    avg_laki: number | null;
    avg_perempuan: number | null;
    gap_pct: number | null;
    suppressed: boolean;
  }[];
  min_group?: number;
}

// ---------------------------------------------------------------------------
// PAY-014: Final pay & pesangon
// ---------------------------------------------------------------------------
export interface PayFinalBracket {
  id: string;
  component: string; // pesangon | upmk
  min_years: number;
  max_years: number | null;
  months: number;
}

export interface PayFinalReasonFactor {
  id: string;
  reason: string;
  pesangon_factor: number;
  upmk_factor: number;
  uph_included: boolean;
  pkwt_compensation: boolean;
}

export interface PayFinalConfig {
  brackets: PayFinalBracket[];
  reason_factors: PayFinalReasonFactor[];
}

export interface PayFinalBreakdown {
  sisa_gaji: number;
  hari_kerja_terpakai: number;
  hari_kerja_sebulan: number;
  sisa_cuti_hari: number;
  sisa_cuti: number;
  pesangon_bulan: number;
  pesangon_faktor: number;
  pesangon: number;
  upmk_bulan: number;
  upmk_faktor: number;
  upmk: number;
  kompensasi_pkwt: number;
  uph_termasuk: boolean;
  faktor_sumber: string;
  adjustments: { label: string; amount: number }[];
}

export interface PayFinal {
  id: string;
  employment_id: string;
  person_name: string | null;
  termination_date: string;
  reason: string;
  years_of_service: number;
  monthly_wage: number;
  breakdown: PayFinalBreakdown;
  gross_total: number;
  loan_deduction: number;
  tax_amount: number;
  net_amount: number;
  status: string; // draft | finalized | paid
  notes: string | null;
  created_at: string;
  finalized_at: string | null;
  paid_at: string | null;
}

export interface PayFinalPreview {
  employment_id: string;
  person_name: string | null;
  termination_date: string;
  reason: string;
  years_of_service: number;
  monthly_wage: number;
  breakdown: PayFinalBreakdown;
  gross_total: number;
  loan_deduction: number;
  tax_amount: number;
  net_amount: number;
}

export interface PayFinalCandidate {
  employment_id: string;
  person_id: string;
  person_name: string;
  termination_date: string | null;
  reason: string | null;
  has_final_pay: boolean;
}
