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
