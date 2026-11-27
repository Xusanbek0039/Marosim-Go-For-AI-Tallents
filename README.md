# MarosimGo — for AI Talents

**MarosimGo** — O'zbekistondagi to'y va oilaviy marosimlar uchun raqamli platforma. Foto/video
studiyalar marosim video va rasmlarini faqat kuyov-kelin va ular taklif qilgan mehmonlar ochadigan
yopiq galereyaga joylaydi. Kuyov-kelinlar to'yxona topib bron qiladi, AI yordamida to'y rejasi va
byudjetini tuzadi, to'y liboslarini AI bilan **o'zida kiyib ko'radi** va sotib oladi. Platforma
xodimlari hammasini admin paneldan boshqaradi.

Bu repozitoriy hakaton uchun topshirilgan ish. U ochiq kodli
[Marosim-Go](https://github.com/Xusanbek0039/Marosim-Go) (MIT) loyihasi ustiga qurilgan. Nima meros
qolgani va nima yangi qo'shilgani [quyida](#meros-va-yangi-qismlar) aniq ko'rsatilgan.

---

## Mundarija

1. [Kim nima qila oladi](#kim-nima-qila-oladi)
2. [Ilovalar](#ilovalar)
3. [Arxitektura](#arxitektura)
4. [Texnologiyalar](#texnologiyalar)
5. [AI imkoniyatlari](#ai-imkoniyatlari)
6. [Premium, narxlar va to'lovlar](#premium-narxlar-va-tolovlar)
7. [Backup tizimi](#backup-tizimi)
8. [Kirim-chiqim (moliya)](#kirim-chiqim-moliya)
9. [Ishga tushirish](#ishga-tushirish)
10. [Muhim sozlamalar (.env)](#muhim-sozlamalar-env)
11. [Fon vazifalari (cron)](#fon-vazifalari-cron)
12. [Foydali buyruqlar](#foydali-buyruqlar)
13. [Testlar](#testlar)
14. [Hujjatlar](#hujjatlar)
15. [Meros va yangi qismlar](#meros-va-yangi-qismlar)

---

## Kim nima qila oladi

| Rol | Imkoniyatlar |
|---|---|
| **Kuyov-kelin (USER)** | Marosim galereyasini ko'rish, mehmonlarni muddatli (24 soat – 1 oy) taklif qilish, to'yxona qidirish va bron qilish, AI maslahatchi bilan to'y rejasi va byudjet, kamera orqali kiyib ko'rish (AR), **AI Fashion Studio** (rasm va video), libos buyurtma qilish, Premium obuna, bildirishnomalar |
| **Studiya (STUDIO)** | Marosim yaratish, Google Drive'ga to'g'ridan-to'g'ri katta video/rasm yuklash, kuyov-kelinni taklif qilish, portfolio va reels, mijozlar bilan chat, Premium (galichka) |
| **To'yxona (VENUE_OWNER)** | Zallar, smenalar, narxlar va bandlik kalendari, bronlarni boshqarish, galereya, sharhlar, Premium (galichka) |
| **Admin** | Super Admin bergan ruxsatlar doirasida: foydalanuvchilar, studiyalar, to'yxonalar, obunalar, kirim-chiqim, Backup, so'rovlar, AI, virtual kiyim katalogi, yordam |
| **Super Admin** | Hamma narsa, shu jumladan adminlar va ularning ruxsatlari, Google Drive ulanishi, API Developer Center, monitoring |

Ruxsatlar katalogi: `backend/apps/accounts/permissions_catalog.py` (har bir modul uchun `*.view`,
`*.create`, `*.update`, … kodlari).

## Ilovalar

| Ilova | Kimlar uchun | Dev port | Production manzil |
|---|---|---|---|
| `backend/` — Django REST API | barcha panellar va mobil ilova | 8000 | `api.marosimgo.uz` |
| `frontend/` — Super Admin va Admin paneli | platforma xodimlari | 3000 | `superadmin.` / `admin.marosimgo.uz` |
| `frontend-studio/` — Studiya kabineti | studiyalar (OWNER / MANAGER / UPLOADER) | 3001 | `studio.marosimgo.uz` |
| `frontend-user/` — Foydalanuvchi kabineti | kuyov-kelin va mehmonlar | 3002 | `userlogin.marosimgo.uz` |
| `frontend-toyxona/` — To'yxona kabineti | to'yxonalar (OWNER / MANAGER / SCHEDULER / VIEWER) | 3003 | `toyxona.marosimgo.uz` |

Productionda Next.js ilovalari **statik eksport** qilinadi va ularni Django o'zi beradi
(`backend/panel*/`, `config/panel.py`). Bitta cPanel/Passenger deploy API'ni ham, barcha panellarni
ham qamrab oladi. Har bir panel o'z domenidagi `/api/v1/` ga murojaat qiladi, shuning uchun httpOnly
auth cookie'lari first-party bo'lib qoladi.

## Arxitektura

```
 Brauzer (4 ta panel)  ──/api/v1──►  Django REST API  ──►  SQLite / PostgreSQL
        │                              │
        │ katta fayllar (resumable)    ├──►  Google Drive (marosim media, zaxira nusxalar)
        └──────────────────────────────┤
                                       ├──►  fal.ai   (AI video va rasm kiyib ko'rish)
                                       ├──►  OpenAI / Anthropic (AI maslahatchi)
                                       └──►  Decart   (jonli AI kiyib ko'rish, ixtiyoriy)
```

Backend modullari (`backend/apps/`):

| Modul | Vazifasi |
|---|---|
| `accounts` | Telefon raqam bilan kirish, JWT (httpOnly cookie), rollar, ruxsatlar, JSHSHIR shifrlash |
| `ceremonies` | Marosimlar, egalik (kuyov/kelin), muddatli mehmon kirishi, takliflar |
| `media` | Drive'ga resumable yuklash, ko'rish/yuklab olish, ffmpeg bilan logo (watermark), o'chirish so'rovlari |
| `storage` | Google Drive OAuth (PKCE, `drive.file`), papkalar, kalitlar seyfi |
| `studios` | Studiyalar, a'zolar, portfolio, reels, reaksiya va izohlar |
| `venues` | To'yxonalar, zallar, smenalar, narxlar, bron, ommaga chiqarish tasdig'i |
| `reviews` | To'yxona va studiyalar sharhlari, moderatsiya |
| `subscriptions` | Premium tariflar, to'lov so'rovlari va tasdig'i, biznes majburiy to'lovi, **kirim-chiqim** |
| `backup` | **Backup rejimi**, bepul muddatlar, ilova ichidagi bildirishnomalar |
| `virtual_tryon` | Kiyim katalogi, AR kiyib ko'rish, AI rasm/video kiyib ko'rish, AI limitlari, buyurtmalar |
| `event_planner` | AI maslahatchi: to'y rejasi, byudjet, to'yxona/studiya tavsiyalari |
| `support` | Yordam xatlari, hamkorlik arizalari |
| `dashboard`, `monitoring`, `devcenter`, `audit` | Statistika, API monitoring, OpenAPI Developer Center, audit logi |

Batafsil: [ARCHITECTURE.md](ARCHITECTURE.md), [docs/STORAGE_ARCHITECTURE.md](docs/STORAGE_ARCHITECTURE.md).

## Texnologiyalar

| Qatlam | Stek |
|---|---|
| Backend | Python 3.12+, Django 5.2, Django REST Framework, SimpleJWT, drf-spectacular, django-filter |
| Ma'lumotlar bazasi | Standart: SQLite (WAL). `DATABASE_URL` orqali kod o'zgartirmasdan PostgreSQL |
| Frontendlar | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query, React Hook Form + Zod, Motion |
| Saqlash | Google Drive (OAuth 2.0, `drive.file`, PKCE), brauzerdan Drive'ga resumable yuklash |
| Media | Pillow, ffmpeg (video watermark, kadr ajratish, normalizatsiya) |
| AI | fal.ai (Kling O3, FASHN, Seedream, LTX), OpenAI / Anthropic, Decart, brauzerda MediaPipe |

## AI imkoniyatlari

### AI Fashion Studio (`frontend-user` → `/ai-studio`)

Foydalanuvchi katalogdan libos tanlaydi, kamerani yoqadi va:

- **Rasm** — kamera kadri ustida libos kiydiriladi (fal.ai **FASHN v1.6**, ~10–20 soniya).
- **Video (4 soniya)** — foydalanuvchi o'zi yozgan videoda kiyimi almashtiriladi (fal.ai
  **Kling O3 video edit**). Yuz, soch, fon va **haqiqiy harakatlar** (qo'l ko'tarish, burilish)
  o'zgarmaydi. Render 3–10 daqiqa davom etadi va **fon job** sifatida ishlaydi: brauzer holatni
  so'rab turadi, tab yopilsa ham tayyor video "Saqlangan obrazlar"ga tushadi
  (`finalize_video_jobs`). Bitta job hech qachon qayta yuborilmaydi, ya'ni pul ikki marta yechilmaydi.
- Natijani 0.5x tezlikda ko'rish, MP4 yuklab olish (Premium'da logosiz) va libosni **sotib olish**
  mumkin.

Video uchun ikkinchi, tez (~1 daqiqa) usul ham bor: `FAL_TRYON_VIDEO_PIPELINE=fast`. Unda bitta
kadr kiyintiriladi (Seedream) va undan video yasaladi (LTX). Bu usul tez ishlaydi, lekin harakatni
AI qayta yaratadi, shuning uchun standart usul `kling`.

Jonli rejim: `DECART_API_KEY` bo'lsa, kamera WebRTC orqali Decart `lucy-vton` ga oqadi.
Batafsil: [docs/AI_FASHION_STUDIO.md](docs/AI_FASHION_STUDIO.md).

### AI maslahatchi (`/ai-reja`)

To'y rejasi, byudjet kalkulyatori va platformadagi to'yxona/studiyalardan tavsiyalar. Provayder va
model admin paneldan tanlanadi (standart: OpenAI). Har bir so'rovning token sarfi va narxi
yoziladi. Batafsil: [docs/AI_EVENT_PLANNER.md](docs/AI_EVENT_PLANNER.md).

### Kamera orqali kiyib ko'rish (`/kiyib-korish`)

AI'siz AR: brauzer MediaPipe bilan tanani kuzatadi va kiyimning shaffof qatlamlarini chizadi.
Kamera kadrlari serverga yuborilmaydi.

## Premium, narxlar va to'lovlar

To'lovlar hozircha qo'lda qabul qilinadi: foydalanuvchi to'laydi va so'rov yuboradi, admin esa
"Obunalar" bo'limida to'lovni qayd etib tasdiqlaydi. Narxlar va limitlar admin paneldan o'zgartiriladi.

**Foydalanuvchi Premium** (AI xarajatlari asosida hisoblangan, limit to'liq ishlatilganda ham
foyda ≥40%):

| Tarif | Narx | AI video / oy | AI rasm / oy | Ulashish |
|---|---|---|---|---|
| Bepul | 0 | — | 3 | 5 kishi |
| 1 oy | 59 000 so'm | 2 | 15 | 15 kishi |
| 3 oy | 159 000 so'm | 2 | 15 | 20 kishi |
| 1 yil | 549 000 so'm | 2 | 10 | 30 kishi |
| 5 yil | 1 990 000 so'm | 1 | 8 | 50 kishi |

Premium'ga logosiz video va rasmlar, yuklab olish, profil galichkasi va AI natijalarini logosiz
yuklab olish ham kiradi. Xato bilan tugagan AI ishlov limitdan ayirilmaydi.

**Bizneslar uchun majburiy oylik to'lov** (bu ularning Premium'i yoki galichkasi):

| Kim | Oyiga | 12 oyga |
|---|---|---|
| To'yxona | 300 000 so'm | 3 240 000 so'm |
| Studiya | 150 000 so'm | 1 620 000 so'm |

To'lov muddati tugagach 7 kunlik muhlat beriladi. Keyin biznes **ommaviy katalogdan va AI
tavsiyalaridan yashiriladi**, lekin panelga kirish yopilmaydi: panelda "To'lov kerak" banneri
chiqadi. To'lov tasdiqlanishi bilan biznes katalogga qaytadi.

AI xarajat birliklari (`settings.PLATFORM_COSTS`, +10% zaxira bilan): AI video ≈ $0.63, AI rasm
$0.075, bulut xotira $0.005 / GB·oy. Dollar kursi admin paneldan o'zgartiriladi.

## Backup tizimi

Kuyov-kelin akkauntlari uchun (`apps/backup`):

1. **Bepul muddat:** marosimga **birinchi video joylangan kundan** boshlab 3 oy.
2. Muddat tugaganda Premium bo'lmasa, akkaunt **avtomatik Backup rejimiga** o'tadi. Marosimlarni
   foydalanuvchi ham, u ulashgan mehmonlar ham ko'ra olmaydi, ularni **faqat Admin va Super Admin**
   ko'radi va boshqaradi. Hech narsa o'chirilmaydi.
3. **Premium sotib olinsa**, akkaunt Backup'dan darhol chiqadi. Premium faol bo'lgan paytda Backup'ga
   o'tkazib bo'lmaydi.
4. **Premium tugasa**, foydalanuvchiga bildirishnoma boradi va yana 3 oy muhlat beriladi. Bir vaqtda
   faqat bitta muhlat bo'ladi.
5. Har bir hodisa bo'yicha ilova ichida **bitta** bildirishnoma yuboriladi (qo'ng'iroqcha va banner).

Admin panel → **Backup**: holatlar (Bepul muddatda / Premium / Backupda / Video yo'q), muddatlar,
Backup'dan chiqarish, muddat va Premium'ni uzaytirish, Backup'ga o'tkazish, foydalanuvchining
video-rasmlarini ko'rish va o'chirish. Ruxsatlar: `backup.view` va `backup.manage`.

## Kirim-chiqim (moliya)

Admin panel → **Kirim-chiqim** (`finance.view`, `finance.manage`):

- oy bo'yicha kirim (Premium, studiyalar, to'yxonalar), chiqim va sof foyda;
- so'nggi 6 oy grafigi va jadvali;
- **AI xarajatlari avtomatik hisoblanadi**: har bir AI video/rasm, AI maslahatchi tokenlari va jonli rejim soniyalari;
- qo'lda xarajat kiritish: server, Google Drive, reklama, ish haqi;
- majburiy to'lov qarzdorlari ro'yxati;
- har bir tarifning foyda ulushi (35% dan past bo'lsa ogohlantiradi);
- dollar kursini o'zgartirish.

## Ishga tushirish

### Backend

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # so'ng haqiqiy maxfiy kalitlar yarating (INSTALLATION.md)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

`.env` o'zgartirilgandan keyin serverni **to'liq** qayta ishga tushiring (Ctrl+C →
`runserver`). Avto-reload `.env` dagi yangi qiymatlarni o'qimaydi.

### Frontendlar

```bash
cd frontend                         # yoki frontend-studio / frontend-user / frontend-toyxona
npm ci
echo BACKEND_URL=http://127.0.0.1:8000 > .env.local
npm run dev                         # 3000 / 3001 / 3002 / 3003
```

### Hammasini mahalliy tarmoqda (LAN demo)

```bash
bash start-lan.sh
```

Har bir port bitta panelni beradi: 8000 — Super Admin (`/` — landing), 8001 — Admin,
8002 — Studiya, 3002 — Foydalanuvchi, 3003 — To'yxona. Foydalanuvchi va to'yxona panellari statik
build'dan ishlaydi, shuning uchun avval `npm run build:panel` qiling.

### Demo akkauntlar

```bash
python manage.py seed_demo            # faqat DEBUG: demo foydalanuvchilar, adminlar, studiyalar
python manage.py seed_tryon_demo      # virtual kiyim katalogi
```

To'liq yo'riqnoma, PostgreSQL va Google Drive sozlamalari: **[INSTALLATION.md](INSTALLATION.md)**,
[docs/GOOGLE_DRIVE_SETUP.md](docs/GOOGLE_DRIVE_SETUP.md), [docs/DEPLOY.md](docs/DEPLOY.md).

## Muhim sozlamalar (.env)

Asosiy o'zgaruvchilar `.env.example` da va [INSTALLATION.md](INSTALLATION.md) da. Quyidagilarning
ko'pchiligi standart qiymat bilan `backend/config/settings.py` da turadi. Ularni o'zgartirish uchun
`backend/.env` ga qo'shing:

| O'zgaruvchi | Standart | Ma'nosi |
|---|---|---|
| `FAL_KEY` | — | fal.ai kaliti: AI rasm va video kiyib ko'rish |
| `FAL_TRYON_VIDEO_PIPELINE` | `kling` | `kling` haqiqiy harakatni saqlaydi (3–10 daq); `fast` ~1 daqiqa ishlaydi, harakatni AI yaratadi |
| `FAL_TRYON_PHOTO_MODEL` / `FAL_TRYON_VIDEO_MODEL` | FASHN v1.6 / Kling O3 edit | Modellar |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | AI maslahatchi (va rasm uchun zaxira provayder) |
| `DECART_API_KEY` | — | Jonli AI kiyib ko'rish (ixtiyoriy) |
| `AI_FREE_PHOTOS_PER_MONTH` | `3` | Premium'siz oylik AI rasm limiti |
| `COST_AI_VIDEO_USD`, `COST_AI_PHOTO_USD` | `0.63`, `0.075` | Xarajat hisobi uchun birlik narxlar |
| `BUSINESS_VENUE_MONTHLY_FEE` / `BUSINESS_STUDIO_MONTHLY_FEE` | `300000` / `150000` | Bizneslar oylik to'lovi |
| `BUSINESS_BILLING_GRACE_DAYS` | `7` | To'lovdan keyingi muhlat (kun) |
| `BACKUP_FREE_MONTHS` | `3` | Backup'dan oldingi bepul muddat (oy) |

Productionda bo'sh yoki namunaviy maxfiy kalitlar bilan server ishga tushmaydi
(`config/secret_guard.py`). Yangi kalitlar yaratish uchun: `python tools/generate_secrets.py`.

## Fon vazifalari (cron)

Productionda cPanel Cron'ga qo'shing (`backend/` ichida, virtual muhit Python'i bilan):

| Buyruq | Qanchada | Vazifasi |
|---|---|---|
| `python manage.py finalize_video_jobs` | har 1–2 daqiqa | Tayyor AI videolarni saqlaydi (tab yopilgan bo'lsa ham) |
| `python manage.py run_backup_cycle` | har 15 daqiqa | Backup'ga o'tkazish/chiqarish, bildirishnomalar |
| `python manage.py process_watermarks` | har 5 daqiqa | Videolarga logo qo'shish (ffmpeg) |
| `python manage.py expire_media_uploads` | har soat | Tugallanmagan yuklashlarni yopish |
| `python manage.py expire_ceremony_invitations` | har soat | Muddati o'tgan takliflar |
| `python manage.py prune_request_logs` | kuniga 1 marta | Eski API monitoring loglarini tozalash |

## Foydali buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `grant_ai_quota 934243408 --videos 10` | Foydalanuvchiga shu oy uchun qo'shimcha AI video/rasm limiti |
| `import_ai_garments` | AI kiyib ko'rish uchun kiyimlarni import qilish |
| `check_ai_tryon` | AI provayderlar sozlamasini tekshirish |
| `storage_selftest`, `google_oauth_check` | Google Drive ulanishini tekshirish |
| `set_phone` | Eski akkauntga telefon raqam biriktirish |
| `rotate_encryption_keys` | JSHSHIR, takliflar va Drive tokenlarini yangi kalitlar bilan qayta shifrlash |
| `api_contract --write`, `export_api_endpoints` | API kirish shartnomasi va endpointlar ro'yxatini yangilash |

## Testlar

```bash
cd backend && pytest                                   # ~4 000 test (3 989)
cd backend && ruff check . && ruff format --check .
cd frontend-user && npm test
cd frontend && npm test
cd <istalgan frontend> && npx tsc --noEmit && npm run lint && npm run build
```

Haqiqiy Next.js proksilari orqali end-to-end tekshiruvlar:
[INSTALLATION.md → End-to-end tests](INSTALLATION.md#end-to-end-tests). CI hammasini
`.github/workflows/` da ishga tushiradi (backend, 4 ta frontend, maxfiy kalitlar skaneri).

## Hujjatlar

| Hujjat | Mazmuni |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | O'rnatish, muhit, ma'lumotlar bazasi, ilovalarni ishga tushirish, testlar |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Tizim tuzilishi, modullar, autentifikatsiya, ma'lumot oqimi |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | API qoidalari, xatolar; to'liq ro'yxat: [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md), [docs/openapi.yaml](docs/openapi.yaml) (342 operatsiya) |
| [docs/AI_FASHION_STUDIO.md](docs/AI_FASHION_STUDIO.md) | AI kiyib ko'rish |
| [docs/AI_EVENT_PLANNER.md](docs/AI_EVENT_PLANNER.md) | AI maslahatchi |
| [docs/CEREMONY_OWNERSHIP.md](docs/CEREMONY_OWNERSHIP.md) | Marosim egaligi va mehmonlar |
| [docs/VENUE_AVAILABILITY.md](docs/VENUE_AVAILABILITY.md) | To'yxona bandligi va bron |
| [docs/STORAGE_ARCHITECTURE.md](docs/STORAGE_ARCHITECTURE.md), [docs/GOOGLE_DRIVE_SETUP.md](docs/GOOGLE_DRIVE_SETUP.md) | Google Drive saqlash |
| [docs/DEPLOY.md](docs/DEPLOY.md) | cPanel/Passenger'ga deploy |
| [docs/SECURITY_INCIDENT_RESPONSE.md](docs/SECURITY_INCIDENT_RESPONSE.md) | Kalitlarni almashtirish va hodisalarga javob |
| [CHANGELOG.md](CHANGELOG.md) | O'zgarishlar tarixi |
| [docs/README.uz.md](docs/README.uz.md) | Asl loyiha hujjati |

## Meros va yangi qismlar

**Meros qilib olingan.** Birinchi commit (`chore: import Marosim-Go baseline…`) — asl loyihaning
[`c12be31d`](https://github.com/Xusanbek0039/Marosim-Go/commit/c12be31d713ff363e472ac4630c0d684f40bf386)
commit'i, fayllar daraxti bayt-ba-bayt bir xil (git tree `b303ef23`). Unga Django API, to'rtta
frontend, RBAC, marosim/taklif/egalik, Google Drive saqlash, media yuklash va watermark, to'yxona va
bron, studiyalar, sharhlar, obunalar, yordam, AR kiyib ko'rish, monitoring va 2 861 ta backend testi
kiradi.

**Shu repozitoriyda qo'shilganlar:**

| Soha | O'zgarish |
|---|---|
| AI | **AI Fashion Studio**: fal.ai orqali rasm va 4 soniyalik video kiyib ko'rish, fon video joblari (pul ikki marta yechilmaydi, tab yopilsa ham video saqlanadi), libos buyurtmasi |
| AI | **AI maslahatchi**: to'y rejasi, byudjet, tavsiyalar, token sarfi hisobi |
| Biznes | **Premium narxlari** real AI xarajatlari asosida, oylik AI limitlari, admin bonus limitlari (`grant_ai_quota`) |
| Biznes | To'yxona va studiyalar uchun **majburiy oylik to'lov**, to'lamaganlarni katalogdan yashirish, panel banneri |
| Biznes | Admin panelda **Kirim-chiqim**: kirim, avtomatik AI xarajatlari, qo'lda xarajatlar, qarzdorlar, tarif iqtisodi |
| Biznes | **Backup tizimi**: bepul muddat, avtomatik Backup, ilova ichidagi bildirishnomalar, admin boshqaruvi |
| UI | AI Studio uchun real inson ishtirokidagi qo'llanma videosi (`frontend-user/public/videos/`) |
| Xavfsizlik | Productionda bo'sh yoki namunaviy kalitlar bilan ishga tushmaslik (`config/secret_guard.py`), `rotate_encryption_keys`, `tools/generate_secrets.py`, hodisalarga javob qo'llanmasi |
| CI | Frontend workflow (4 ilova), maxfiy kalitlar skaneri, backend uchun qattiqroq tekshiruvlar (format, migratsiyalar, OpenAPI) |
| Tuzatishlar | Backend lint xatolari, `frontend-user` lint, 4 ta ro'yxat endpointida N+1 so'rovlar, dialog tugmalari UI |
| Hujjatlar | OpenAPI yangilandi, README, INSTALLATION, ARCHITECTURE, API_DOCUMENTATION, CHANGELOG |

## Litsenziya

MIT. Asl ish © 2026 Husanbek Suyunov, [LICENSE](LICENSE). Shu repozitoriydagi o'zgarishlar ham shu
litsenziya ostida.
