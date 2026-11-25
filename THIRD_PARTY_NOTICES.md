# Third-party notices

MarosimGo itself is MIT-licensed (see [LICENSE](LICENSE)). This file lists third-party material
that is **checked into this repository**, and the licences of the dependencies installed from
npm and PyPI.

## Checked-in third-party files

| Files | Project | Licence | Licence text |
|---|---|---|---|
| `backend/landing/vendor/three.core.js`, `three.module.js`, `RoomEnvironment.js` | [three.js](https://threejs.org) © 2010-2025 three.js authors | MIT | [`backend/landing/vendor/THREE-LICENSE.txt`](backend/landing/vendor/THREE-LICENSE.txt) |
| `*/fonts/jakarta-latin*.woff2` (frontends, landing, and copies inside the `backend/panel*/` builds) | [Plus Jakarta Sans](https://github.com/tokotype/PlusJakartaSans) © 2020 The Plus Jakarta Sans Project Authors | SIL Open Font License 1.1 | [`licenses/PlusJakartaSans-OFL.txt`](licenses/PlusJakartaSans-OFL.txt) (verbatim from the font project) |
| `frontend-user/public/mediapipe/pose_landmarker_lite.task` | [MediaPipe](https://github.com/google-ai-edge/mediapipe) Pose Landmarker model, Google | Apache-2.0 | <https://www.apache.org/licenses/LICENSE-2.0> |
| `frontend/src/components/ui/*.tsx` | generated from the [shadcn/ui](https://ui.shadcn.com) registry and adapted | MIT | <https://github.com/shadcn-ui/ui/blob/main/LICENSE.md> |

The MediaPipe **wasm runtime** is not checked in. `frontend-user/scripts/prepare-mediapipe.mjs`
copies it from the installed `@mediapipe/tasks-vision` package (Apache-2.0) at build time.

## Installed dependencies (direct)

All direct dependencies use permissive or weak-copyleft licences compatible with MIT
distribution. Versions are pinned in `backend/requirements*.txt` and the `package-lock.json` files.

**Python:** Django, djangorestframework, drf-spectacular, django-filter (BSD-3-Clause); argon2-cffi,
django-cors-headers, django-environ, djangorestframework-simplejwt (MIT); cryptography
(Apache-2.0 OR BSD-3-Clause); google-api-python-client, google-auth, google-auth-httplib2,
google-auth-oauthlib, phonenumbers (Apache-2.0); pillow (MIT-CMU); imageio-ffmpeg (BSD-2-Clause;
its wheels bundle an ffmpeg binary under ffmpeg's own licence, used server-side only);
**psycopg (LGPL-3.0)**, used unmodified as a library.

**npm:** next, react, react-dom, @tanstack/react-query, react-hook-form, @hookform/resolvers,
zod, radix-ui, motion, sonner, next-themes, tailwindcss, @tailwindcss/turbopack, tw-animate-css,
shadcn, cn, eslint, eslint-config-next, server-only, @types/* (MIT); typescript,
class-variance-authority, @mediapipe/tasks-vision (Apache-2.0); lucide-react (ISC).

## Origin of the application code

The application code comes from the upstream MIT project
[Xusanbek0039/Marosim-Go](https://github.com/Xusanbek0039/Marosim-Go) (© 2026 Husanbek Suyunov),
imported unchanged at commit `c12be31d`. The changes made in this repository are listed in
[CHANGELOG.md](CHANGELOG.md) and in the README section *What is inherited and what is new*.
