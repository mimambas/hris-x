#!/usr/bin/env python3
"""Seed data absensi September 2026 di database staging HRIS-X untuk UAT modul Absensi.

Lewat REST API backend staging (Vercel), karena koneksi TCP Postgres langsung
dari VM sandbox di-intercept proxy. Pola sama seperti seed_payroll_staging.py:
login -> panggil endpoint dengan retry (cold start Vercel 10-115 dtk).

Penggunaan:
    python3 backend/scripts/seed_attendance_staging.py

Idempoten: record untuk (employment, tanggal) yang sudah ada di-skip.

Data (hari kerja Senin-Jumat September 2026, TIDAK termasuk 1 Okt 2026):
- Shift "pagi" (08:00-17:00, grace 15 mnt) sudah ter-assign ke semua employment
  via seed.py, jadi check-in > 08:15 tercatat "late".
- Andi Pratama : 1x mangkir (2026-09-09), sisanya hadir ~08:05-08:12
- Budi Santoso : 2x terlambat (09-03 08:40, 09-17 08:50), 1x mangkir (09-24)
- Dewi Lestari : 1x terlambat (09-10 08:35), sisanya hadir
- Sari Wijaya  : 1x mangkir (09-15), sisanya hadir
Rina Kartika di-skip (employment warisan 'contract', bukan aktif).

HANYA tenant staging 'hashiru'. Tidak menyentuh tenant lain.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, timedelta

BASE = "https://hris-x-backend-staging.vercel.app/api/v1"
TENANT_SLUG = "hashiru"
ADMIN_EMAIL = "admin@hashiru.id"
ADMIN_PASSWORD = "Password123!"
TIMEOUT = 300

# (nama, tanggal_mangkir, {tanggal: jam_masuk_terlambat})
PLAN = {
    "Andi Pratama": ({"2026-09-09"}, {}),
    "Budi Santoso": ({"2026-09-24"}, {"2026-09-03": "08:40", "2026-09-17": "08:50"}),
    "Dewi Lestari": (set(), {"2026-09-10": "08:35"}),
    "Sari Wijaya": ({"2026-09-15"}, {}),
}

CHECK_OUT_TIMES = ["17:05", "17:12", "17:20", "17:08", "17:15"]


def call(method, path, token=None, body=None, retries=4):
    import http.client
    import socket as _socket
    data = json.dumps(body).encode() if body is not None else None
    last = (0, "tidak ada respons")
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(raw) if "json" in ctype else raw)
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode(errors="replace")[:500]
            except Exception:
                return e.code, f"HTTP {e.code} (body tidak terbaca)"
        except (http.client.RemoteDisconnected, http.client.IncompleteRead,
                _socket.timeout, TimeoutError, ConnectionError,
                urllib.error.URLError) as e:
            last = (0, f"transien ({type(e).__name__})")
            print(f"   percobaan {attempt}: {last[1]}, ulangi ...", flush=True)
            time.sleep(10 * attempt)
    return last


def weekdays_sept_2026():
    days, d = [], date(2026, 9, 1)
    while d.month == 9:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def checkout(emp_id, iso, jam_pulang, token):
    """Check-out; anggap sukses bila 200/201 atau 422 'sudah check-out'.

    Jam dikirim sebagai waktu lokal-naif (tanpa offset, konvensi ADR-0008):
    "2026-09-01T17:05:00" berarti 17:05 waktu lokasi kerja.
    """
    sc, body = call("POST", "/attendance/check-out", token, {
        "employment_id": emp_id,
        "at": f"{iso}T{jam_pulang}:00", "source": "web"})
    ok = sc in (200, 201) or (sc == 422 and "Sudah check-out" in str(body))
    if not ok:
        print(f"   GAGAL check-out {iso}: {sc} {body}", flush=True)
    return ok


def main() -> int:
    print("1. Login staging ...", flush=True)
    sc, login = call("POST", "/auth/login", body={
        "tenant_slug": TENANT_SLUG, "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD})
    assert sc == 200, f"login gagal: {sc} {login}"
    token = login["access_token"]
    print("   OK.", flush=True)

    print("2. Ambil person & employment ...", flush=True)
    sc, persons = call("GET", "/persons", token)
    assert sc == 200, f"persons gagal: {sc} {persons}"
    name_to_person = {p["full_name"]: p["id"] for p in persons}
    sc, emps = call("GET", "/employments", token)
    assert sc == 200, f"employments gagal: {sc} {emps}"
    person_to_emp = {e["person_id"]: e for e in emps}

    targets = []
    for name in PLAN:
        pid = name_to_person.get(name)
        emp = person_to_emp.get(pid) if pid else None
        if not emp:
            print(f"   SKIP {name}: tidak ada employment.", flush=True)
            continue
        if emp["status"] not in ("active", "probation"):
            print(f"   SKIP {name}: status={emp['status']}.", flush=True)
            continue
        targets.append((name, emp["id"]))
    print(f"   Target: {len(targets)} karyawan.", flush=True)

    days = weekdays_sept_2026()
    print(f"   Hari kerja Sep 2026: {len(days)} hari.", flush=True)

    hasil = {}
    for idx, (name, emp_id) in enumerate(targets):
        mangkir, lates = PLAN[name]
        print(f"\n3.{idx + 1} {name} ...", flush=True)
        sc, recs = call(
            "GET",
            f"/attendance/records?employment_id={emp_id}"
            f"&date_from=2026-09-01&date_to=2026-09-30", token)
        assert sc == 200, f"records gagal: {sc} {recs}"
        existing = {r["date"] for r in recs}
        dibuat, dilewati = 0, 0
        for i, d in enumerate(days):
            iso = d.isoformat()
            if iso in existing:
                dilewati += 1
                continue
            if iso in mangkir:
                continue  # tanpa record -> terhitung mangkir di summary
            jam_masuk = lates.get(iso) or f"08:{5 + (i % 8):02d}"
            jam_pulang = CHECK_OUT_TIMES[i % len(CHECK_OUT_TIMES)]
            sc, body = call("POST", "/attendance/check-in", token, {
                "employment_id": emp_id,
                "at": f"{iso}T{jam_masuk}:00", "source": "web",
                "reason": "Seed UAT staging"})
            if sc not in (200, 201) and not (
                    sc == 422 and "Sudah check-in" in str(body)):
                print(f"   GAGAL check-in {iso}: {sc} {body}", flush=True)
                continue
            # check-out selalu dicoba: menutup record yang check-in-nya
            # lolos di percobaan yang responsnya hilang (422 di retry)
            if checkout(emp_id, iso, jam_pulang, token):
                dibuat += 1
        hasil[name] = (dibuat, dilewati, emp_id)
        print(f"   dibuat={dibuat}, sudah ada dilewati={dilewati}", flush=True)

    print("\n4. Verifikasi summary 2026-09 ...", flush=True)
    print(f"{'Nama':<16} {'Hadir':>6} {'Terlambat':>10} "
          f"{'Mangkir':>8} {'Cuti':>5} {'Libur':>6}")
    for name, (dibuat, dilewati, emp_id) in hasil.items():
        sc, s = call("GET",
                     f"/attendance/summary?employment_id={emp_id}"
                     f"&period=2026-09", token)
        assert sc == 200, f"summary gagal: {sc} {s}"
        print(f"{name:<16} {s['present']:>6} {s['late']:>10} "
              f"{s['absent']:>8} {s['leave']:>5} {s['holiday']:>6}")
        assert s["present"] > 0, f"{name}: Hadir = 0!"
    print("\nSelesai.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
