#!/usr/bin/env python3
"""Seed SATU periode payroll di database staging HRIS-X untuk UAT slip gaji.

Menjalankan payroll run periode tertentu di tenant staging 'hashiru' lewat
REST API backend staging (Vercel). Dipakai karena koneksi TCP Postgres
langsung dari VM sandbox di-intercept proxy; HTTP ke Vercel lambat
(cold start) tapi berhasil.

Penggunaan:
    python3 backend/scripts/seed_payroll_staging.py [YYYY-MM]   # default 2026-09

Langkah:
  1. Login sebagai admin staging -> JWT.
  2. Cek run periode tsb (idempoten: pakai ulang bila sudah ada).
  3. POST /payroll/runs -> draft, lalu POST .../lock -> locked.
  4. GET lines -> ringkasan angka per karyawan (sanity check).
  5. GET slip PDF satu karyawan -> /tmp untuk verifikasi render.

HANYA tenant staging 'hashiru'. Tidak menyentuh tenant lain.
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "https://hris-x-backend-staging.vercel.app/api/v1"
TENANT_SLUG = "hashiru"
ADMIN_EMAIL = "admin@hashiru.id"
ADMIN_PASSWORD = "Password123!"
PERIOD = sys.argv[1] if len(sys.argv) > 1 else "2026-09"
TIMEOUT = 300


def call(method: str, path: str, token: str | None = None,
         body: dict | None = None, retries: int = 4):
    import time
    import http.client
    import socket as _socket
    data = json.dumps(body).encode() if body is not None else None
    last: tuple = (0, "tidak ada respons")
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(raw)
                                     if "json" in ctype else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:500]
        except (http.client.RemoteDisconnected, http.client.IncompleteRead,
                _socket.timeout, TimeoutError, ConnectionError,
                urllib.error.URLError) as e:
            last = (0, f"transien ({type(e).__name__})")
            print(f"   percobaan {attempt} {last[1]}, ulangi ...", flush=True)
            time.sleep(10 * attempt)
    return last


def main() -> int:
    print("1. Login staging ...", flush=True)
    sc, login = call("POST", "/auth/login", body={
        "tenant_slug": TENANT_SLUG, "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD})
    assert sc == 200, f"login gagal: {sc} {login}"
    token = login["access_token"]
    print("   OK, token diperoleh.", flush=True)

    print("2. Cek run yang sudah ada ...", flush=True)
    sc, runs = call("GET", "/payroll/runs", token)
    assert sc == 200, f"list runs gagal: {sc} {runs}"
    run = next((r for r in runs if r["period"] == PERIOD), None)
    if run:
        print(f"   Run {PERIOD} sudah ada (status={run['status']}).", flush=True)
    else:
        print(f"3. Buat run {PERIOD} ...", flush=True)
        sc, run = call("POST", "/payroll/runs", token, {
            "period": PERIOD, "include_thr": False})
        assert sc == 201, f"create run gagal: {sc} {run}"
        print(f"   OK: id={run['id']}, headcount={run['headcount']}.",
              flush=True)

    if run["status"] != "locked":
        print("4. Kunci run ...", flush=True)
        sc, run = call("POST", f"/payroll/runs/{run['id']}/lock", token)
        assert sc == 200, f"lock gagal: {sc} {run}"
        print("   OK: locked.", flush=True)
    else:
        print("4. Run sudah locked, lewati.", flush=True)

    print("5. Ambil lines ...", flush=True)
    sc, lines = call("GET", f"/payroll/runs/{run['id']}/lines", token)
    assert sc == 200, f"lines gagal: {sc} {lines}"
    print(f"\n=== Run {PERIOD} | status={run['status']} | "
          f"karyawan={len(lines)} ===")
    print(f"{'Nama':<18} {'Bruto':>12} {'Potongan':>12} "
          f"{'PPh21':>10} {'Take-home':>12}")
    for l in lines:
        print(f"{l['person_name']:<18} {l['gross']:>12,} "
              f"{l['total_deductions']:>12,} {l['pph21']:>10,} "
              f"{l['take_home_pay']:>12,}")
    t = run.get("totals") or {}
    if t:
        print(f"{'TOTAL':<18} {t.get('total_gross',0):>12,} "
              f"{t.get('total_deductions',0):>12,} "
              f"{t.get('total_pph21',0):>10,} "
              f"{t.get('total_take_home',0):>12,}")

    print("\n6. Render slip PDF contoh ...", flush=True)
    emp = lines[0]
    sc, pdf = call("GET",
                   f"/payroll/runs/{run['id']}/payslip/{emp['employment_id']}.pdf",
                   token)
    assert sc == 200 and isinstance(pdf, bytes) and pdf[:4] == b"%PDF", \
        f"slip gagal: {sc} {str(pdf)[:100]}"
    path = f"/tmp/slip-{PERIOD}-{emp['nik']}.pdf"
    open(path, "wb").write(pdf)
    print(f"   OK: {emp['person_name']} -> {path} ({len(pdf)} byte)")
    print("\nSELESAI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
