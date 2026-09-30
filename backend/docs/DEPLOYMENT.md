# Panduan Deployment HRIS-X Backend

Panduan generik — bisa dipakai di VM, container orchestrator, atau PaaS
apapun yang mendukung Docker + Postgres. Dokumen ini **sengaja tidak
menyebut provider free-tier spesifik**: syarat free-tier berubah-ubah dan
beberapa kandidat populer (Koyeb, Render) mewajibkan kartu kredit —
keduanya sudah dicoret dari opsi (keputusan pengguna).

## 1. Arsitektur rilis

- Satu container: FastAPI (uvicorn) — modular monolith, multi-tenant.
- Database: **PostgreSQL** (wajib di produksi; SQLite hanya dev/test).
- RLS Postgres (`migrations/001_rls.sql`) = hardening isolasi tenant
  lapis kedua setelah penegakan di aplikasi (ADR-0003).

## 2. Contoh Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /srv/hrisx
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
WORKDIR /srv/hrisx/backend

# Jangan bake SECRET_KEY / DATABASE_URL ke image.
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers"]
```

Catatan: `--proxy-headers` agar `X-Forwarded-Proto` dari reverse proxy
dibaca — middleware HSTS hanya aktif bila request terdeteksi HTTPS.

Contoh `docker-compose.yml` minimal (app + Postgres):

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: hrisx
      POSTGRES_USER: hrisx_app
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
  api:
    build: .
    environment:
      DATABASE_URL: postgresql+psycopg://hrisx_app:${DB_PASSWORD}@db:5432/hrisx
      SECRET_KEY: ${SECRET_KEY}
      ENV: production
      ALLOWED_ORIGINS: https://hris.contoh.id
      JWT_EXPIRE_MINUTES: 480
    depends_on: [db]
    ports: ["8000:8000"]
volumes:
  pgdata:
```

## 3. Environment variables wajib

| Variabel | Wajib | Default | Catatan |
|----------|-------|---------|---------|
| `DATABASE_URL` | Ya (produksi) | `sqlite:///./hrisx.db` | Format Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `SECRET_KEY` | Ya (bila `ENV=production`) | `dev-only-secret-key-ganti-di-produksi` | Acak ≥32 char; start **ditolak** bila masih default saat `ENV=production` |
| `ENV` | Dianjurkan | `development` | `development`/`staging`/`production` |
| `ALLOWED_ORIGINS` | Bila ada frontend beda origin | *(kosong = tanpa CORS)* | Koma-dipisah, mis. `https://a.id,https://b.id` |
| `JWT_EXPIRE_MINUTES` | Tidak | `480` | Masa berlaku JWT (8 jam) |

## 4. Migrasi database (sekali, sebagai pemilik DB)

```bash
# 1. Buat skema (otomatis via create_all saat app start) ATAU siapkan manual.
# 2. Terapkan RLS:
psql "$DATABASE_URL" -f backend/migrations/001_rls.sql

# 3. Verifikasi (butuh Postgres asli):
DATABASE_URL="$DATABASE_URL" python backend/migrations/verify_rls.py
```

Aturan operasi (ADR-0003):
- Setiap transaksi aplikasi WAJIB `SET LOCAL app.tenant_id='<uuid>'`.
- Role aplikasi hanya diberi GRANT DML (bukan pemilik tabel) agar policy
  dievaluasi.
- **Tabel baru WAJIB didaftarkan manual di whitelist
  `migrations/001_rls.sql`** (pelajaran Sprint 7; Sprint 10 tidak menambah tabel).

Seed data demo (opsional, bukan untuk produksi):

```bash
DATABASE_URL="..." python backend/seed.py   # idempoten; admin: admin@hashiru.id
```

## 5. Backup & restore Postgres (target PRD NFR-014)

```bash
# Backup harian terenkripsi (contoh cron 02:00 WIB):
pg_dump "$DATABASE_URL" -Fc | \
  gpg --symmetric --cipher-algo AES256 --passphrase "$BACKUP_PASSPHRASE" \
  > /backup/hrisx-$(date +%F).dump.gpg

# Restore (uji bulanan — RTO ≤4 jam, RPO ≤15 menit):
gpg --decrypt /backup/hrisx-YYYY-MM-DD.dump.gpg | pg_restore -d "$DATABASE_URL" -c
```

Jadwalkan backup harian + uji restore tiap bulan; simpan salinan di lokasi
terpisah (prinsip 3-2-1).

## 6. Keterbatasan SQLite (dev/test saja)

- Tanpa RLS: isolasi tenant murni di level aplikasi.
- Tanpa tipe Postgres tertentu; SQLAlchemy menjaga portabilitas, tetapi
  uji beban & perilaku konkurensi harus dilakukan di Postgres.
- File DB lokal bukan target backup produksi.

## 7. Operasional

- Health check: `GET /health` → `{"status":"ok","app":"hris-x","sprint":10}`.
- Rate limit login: in-memory per-instance; untuk multi-instance pindahkan
  ke Redis (scope F2).
- Log terstruktur tanpa PII (PRD NFR-034); jangan log password/token.
- Pembekuan rilis ±3 hari sekitar tanggal gajian mayoritas pelanggan
  (PRD NFR-011).
- API docs: `/docs` (OpenAPI). Kompatibilitas API v1 dijaga ≥12 bulan
  setelah versi baru rilis (PRD NFR-036).
