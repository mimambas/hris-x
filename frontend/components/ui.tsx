"use client";

import type { ReactNode } from "react";
import type { LeaveStatus } from "@/lib/types";

// ---------------------------------------------------------------- Spinner
export function Spinner({ label = "Memuat data…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-500">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-brand-600" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

// ---------------------------------------------------------------- ErrorBox
export function ErrorBox({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
      <p className="font-medium">Terjadi kesalahan</p>
      <p className="mt-1 text-sm">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-800"
        >
          Coba lagi
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- EmptyState
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

// ---------------------------------------------------------------- Card
export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

// ---------------------------------------------------------------- PageHeader
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------- StatusChip (cuti & umum)
const LEAVE_STATUS: Record<LeaveStatus, { label: string; cls: string }> = {
  draft: { label: "Draf", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
  submitted: { label: "Menunggu L1", cls: "bg-amber-100 text-amber-800 ring-amber-300" },
  approved_l1: { label: "Menunggu L2", cls: "bg-blue-100 text-blue-800 ring-blue-300" },
  approved: { label: "Disetujui", cls: "bg-green-100 text-green-800 ring-green-300" },
  rejected: { label: "Ditolak", cls: "bg-red-100 text-red-800 ring-red-300" },
  cancelled: { label: "Dibatalkan", cls: "bg-slate-100 text-slate-500 ring-slate-300" },
};

export function StatusChip({ status }: { status: LeaveStatus | string }) {
  const s = LEAVE_STATUS[status as LeaveStatus] ?? {
    label: status,
    cls: "bg-slate-100 text-slate-700 ring-slate-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

export function RunStatusChip({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    draft: { label: "Draf", cls: "bg-slate-100 text-slate-700 ring-slate-300" },
    locked: { label: "Terkunci", cls: "bg-green-100 text-green-800 ring-green-300" },
  };
  const s = map[status] ?? { label: status, cls: "bg-slate-100 text-slate-700 ring-slate-300" };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------- Form primitives
export const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:bg-slate-100";

export function Field({
  label,
  required,
  children,
  hint,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {label} {required && <span className="text-red-600">*</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const btnPrimary =
  "rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60";
export const btnSecondary =
  "rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60";
export const btnDanger =
  "rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60";
export const btnSmall =
  "rounded-md px-2.5 py-1 text-xs font-medium disabled:opacity-60";
