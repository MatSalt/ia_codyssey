# 로컬 로그인·책장·업로드 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자가 선택한 Orca 감독형 실행을 보존한다. 총괄이 Run/Task/worker-start와 편집 소유권·검증·통합을 관리한다.

**Goal:** 외부 계정 없이 개발용 로그인→동의→책장·초안 생성/삭제→사진 업로드·서버 WebP 정규화를 브라우저에서 확인한다.

**Architecture:** 공개 HTTP DTO는 공통계약 v1.3을 유지한다. API는 인증·입력·소유권 경계, application은 정책, repository는 PostgreSQL transaction, adapter는 비공개 로컬 파일을 담당한다. 기존 validate_upload job을 worker에서 실행하고 파일 처리는 transaction 밖에서 수행한다.

**Tech Stack:** 기존 FastAPI/Pydantic/SQLAlchemy/asyncpg/PostgreSQL 17, React/TypeScript/Query/Router, Pillow/pillow-heif. 신규 의존성은 우선 추가하지 않는다.

**Spec:** 기능요구명세서.md, docs/공통계약-v1.md 2~4절, docs/설계.md, 승인된 첫 기반 계획 및 검증 보고서. 2026-10-16 사용자가 외부 자원 준비 전 로컬·가짜 adapter와 이 작업 순서를 승인했다.

## Global Constraints

- 첫 기반 독립 검토의 Critical/Important 문제 해결 후 착수한다.
- OAuth·R2·OpenAI 연결, 유료 호출, 배포는 실행하지 않는다. 기존 moriai는 읽기 전용이며 코드·비밀값·데이터를 이번 묶음에서 복사하지 않는다.
- 개발 로그인은 기본 off, APP_ENV=local 및 DEV_AUTH_ENABLED=true 조합에서만 활성화한다. production과 함께 켜면 시작을 거부한다. UI는 ‘개발용 가짜 로그인’을 표시한다.
- 실제 OAuth callback은 구현 성공으로 가장하지 않는다. 개발 전용 POST /api/dev/login은 두 고정 synthetic 계정만 허용하며 public v1 계약과 구분한다.
- 세션 원문은 DB에 저장하지 않는다. HttpOnly·SameSite=Lax cookie, CSRF·Origin 검사를 적용한다. 계약의 Secure cookie는 실제 배포에 유지하며 로컬 HTTP 예외만 명시적으로 설정한다. 기본 바인딩은 127.0.0.1이다.
- 파일당 20971520 bytes, 사진첩당 314572800 bytes, 사진 1~50장·40000000 pixels. filename을 storage path로 사용하지 않는다.
- 외부 AI를 호출하거나 가짜 AI 생성 결과를 이번 묶음에서 만들지 않는다. HDR/10bit 지원은 미완료로 표시하고 기존 명시적 실패 동작을 유지한다.
- manifests/lock·공통 설정·models/migration·Makefile은 총괄이 지정한 단일 편집자만 변경한다. 공유 checkout에서 작업자는 Git·설치를 수행하지 않는다.

## Review Focus

- 다른 계정의 album/upload/asset ID, 삭제 뒤 재사용한 URL: 파일·메타데이터 모두 404. Task 2/3의 실제 HTTP 검사.
- 동시 동일 Idempotency-Key와 버전이 바뀐 재전송: 한 결과로 수렴하며 요청 hash가 다르면 409. Task 1/2의 두 DB 연결 검사.
- PUT 뒤 bytes 변경·동시 complete·validation 중 삭제: 원본을 확정한 후 검사하고 stale fence의 파생본은 연결하지 않음. Task 3 강제 종료·경합 검사.
- 두 업로드 batch 완료 순서 역전·수동 정렬: selection_index와 date/manual 규칙 유지. Task 3 DB 검사와 Task 4 UI 확인.
- 조작된 개발 로그인·CSRF 누락·허용되지 않은 Origin: production에서 route 비활성화, 변경 요청 거부. Task 1/4 검사.

## Task 1: 세션·동의·공통 HTTP 계약

**Owner:** backend 기반 담당. models/migration·설정의 단일 편집자.

**Files:** Modify backend/models.py, backend/settings.py, backend/main.py, .env.example, compose.yaml. Create backend/migrations/versions/0002_local_upload_flow.py, backend/http/{errors,schemas,security}.py, backend/auth/{repository,service,routes}.py, backend/tests/integration/test_auth_http.py.

**Interfaces:** create_app은 테스트용 settings/session factory 주입을 허용한다. require_user(request) → AuthContext(user_id, session_id), require_csrf(request, context) → None. GET /api/v1/me·POST /consents·POST /auth/logout·GET /client-config는 계약의 envelope/no-store를 따른다. Session 수명은 개발 기본 24시간, 정책 버전은 명시 설정값이며 실제 OAuth 운영 정책 확정을 대신하지 않는다.

- [x] 실제 DB HTTP 테스트 작성: 개발 route 기본 off, production+dev_auth 설정 거부, session token hash 저장·만료·logout 철회, CSRF/Origin 누락 403, 동일 consent 201→200, 다른 계정 독립성.
- [x] 전용 테스트를 실행해 미구현 실패를 확인한다.
- [x] auth_identities·sessions·consents·idempotency_records와 Task 2/3에 필요한 album/page/upload 필드를 단일 migration으로 추가한다. 0001은 수정하지 않는다.
- [x] 개발 auth·공통 오류/request_id/extra=forbid·CSRF를 구현한다. 동의 고지는 원본 보관·AI 처리·삭제·복구 예외를 포함한다.
- [x] migration upgrade/downgrade/upgrade/check와 실제 DB auth 테스트를 통과시킨다. 총괄 검토 후 commit.

## Task 2: 책장·초안·삭제와 멱등성

**Depends:** Task 1. **Owner:** album 담당. migration·공통 설정 편집 금지.

**Files:** Create backend/albums/{repository,service,routes}.py, backend/http/idempotency.py, backend/tests/integration/test_album_http.py. Modify backend/main.py의 router 등록은 총괄이 통합한다.

**Interfaces:** /api/v1/albums GET/POST, /albums/{id} GET/DELETE. create_album(user_id, key, request_hash) → AlbumSummary. get_album_detail(user_id, album_id) → AlbumDetail. delete_album(user_id, album_id, expected_version) → deleted 응답. repository는 transaction 내 소유권·삭제·버전을 검사하고 album_cleanup outbox를 저장한다.

- [x] 테스트 작성: 기본 제목·UUID·UTC·version=1, 동일 키 동시 생성 1개, 다른 요청 hash 409, 삭제 후 키 재전송 404, cursor 경계/동률, 다른 사용자 404, stale delete 409.
- [x] 테스트 실패를 확인하고 repository/application/routes를 구현한다. idempotency 재생은 버전 검사보다 앞서되 소유권·삭제 검사를 생략하지 않는다.
- [x] 삭제는 DB 접근 즉시 차단·비동기 cleanup으로 처리한다. 실제 파일 정리 handler는 Task 3이 담당한다.
- [x] 실제 DB HTTP 테스트와 기존 회귀를 통과시킨 뒤 총괄 commit.

## Task 3: 비공개 로컬 PUT·validation worker·페이지 순서

**Depends:** Task 1/2. **Owner:** media/application 담당. frozen migration·공통 설정은 총괄에게 요청한다.

**Files:** Create backend/storage/{local,signing}.py, backend/uploads/{repository,service,routes,validation}.py, backend/albums/page_order.py, backend/tests/integration/test_upload_http.py, test_validation_worker.py. Modify backend/worker/jobs.py·__main__.py는 기존 소유권을 이전받아 편집한다.

**Interfaces:** LocalStorage는 opaque key의 bounded PUT/read/stat/delete 및 제한된 접근 URL을 제공한다. source URL은 일반 조회에 발급하지 않는다. reservation/complete/status/page delete/page-order/media-access는 v1.3 endpoint/DTO를 따른다. validate_upload(job_claim: backend.worker.jobs.JobClaim) → None은 normalize_in_process를 호출하고 현재 fence·owner/album/page 상태를 확인해 source/normalized/thumbnail을 연결한다.

- [x] 실제 DB 테스트 작성: 미동의 예약 403·행/URL 0개, 50/51장·20MiB/300MiB 경계, 동시 예약 제한, MIME 빈 HEIC 예약, path traversal, 만료/다른 사용자 URL, 선언 bytes 불일치.
- [x] 테스트 실패 확인 후 비공개 local storage·서명·원자 예약을 구현한다. PUT 원본은 확정 후 덮어쓰기를 금지하고 정규화 완료만 ready로 처리한다.
- [x] complete 중복 job 1개, validation 강제 종료→재시작, stale fence/삭제 후 결과 연결 금지·파생본 cleanup 검사를 추가하고 실패를 확인한다.
- [x] 독립 session/heartbeat의 job runner와 validation·cleanup handler를 구현한다. 파일 저장과 subprocess 대기는 DB row lock 밖에서 수행한다.
- [x] EXIF 현지 날짜→File.lastModified Asia/Seoul→예약시각, 동률 selection_index, batch 종료 시 date 정렬, manual 유지·뒤 추가·전체 page-order·실패 페이지 제거를 검증한다.
- [x] 8bit HEIC·투명 PNG·회전 JPEG의 실제 업로드→WebP ready를 통과시킨다. HDR 실패는 명시적으로 표시하며 HEIC 전체 지원 성공으로 보고하지 않는다. 총괄 commit.

## Task 4: 브라우저 흐름 연결·통합 검증

**Depends:** Task 1/2 공개 인터페이스 확정 후 UI를 병렬 진행할 수 있다. **Owner:** frontend 담당, backend/lock 편집 금지.

**Files:** Create frontend/src/api/{client,types}.ts, frontend/src/features/auth/AuthGate.tsx, frontend/src/features/albums/Bookshelf.tsx, frontend/src/features/albums/AlbumEditor.tsx, frontend/src/features/uploads/UploadPanel.tsx, frontend/src/features/uploads/useUploads.ts, frontend/src/styles.css. Modify frontend/src/App.tsx. Browser 검증 방법은 사용 가능한 기존 도구를 확인하고 신규 test dependency는 총괄과 조율한다.

**Interfaces:** frontend는 공개 HTTP만 호출한다. query cache key에 사용자 구분을 포함하고 logout 때 삭제한다. upload는 reservation→required_headers PUT→complete→status polling 순서다.

- [x] 개발 로그인 표시·동의·책장·초안·업로드 진행/실패·서버 썸네일·수동 정렬·삭제 화면을 구현한다. 생성 버튼은 후속 기능임을 표시하며 가짜 성공으로 이동하지 않는다.
- [x] Idempotency-Key는 사용자 의도 한 번에 생성하고 네트워크 재전송에 재사용한다. 만료/401/409는 입력을 보존하고 최신값과 비교하도록 처리한다.
- [x] 실제 로컬 브라우저에서 두 사용자 격리, 동의 거절, 다중 파일·HEIC 미리보기 대체, 실패 제거, reload·재시도·삭제를 확인한다. 빌드·전체 DB 회귀·기존 격리 검증을 통과시킨다.
- [x] 독립 Orca 검토 후 Critical/Important를 수정한다. README에 실제 실행 방법, dev auth 표시/한계·HDR 미완료·외부 연동 미실행을 기록하고 총괄 commit.

## 자체 점검과 완료 경계

로그인·동의(Task 1), 책장/초안/삭제(Task 2), 업로드·순서·접근·복구(Task 3), UI(Task 4)로 각 요구와 다섯 Review Focus를 배정했다. DTO·순서는 공통계약을 재정의하지 않는다. 다음 묶음은 가짜 AI 생성→review_ready→글귀 수정→publish→뷰어이며 이번 완료로 이를 성공 처리하지 않는다. 실제 OAuth 세션 운영 정책·HDR tone mapper·실제 제공자 검증은 별도 검토 대상이다.

2026-10-16 사용자 계획 검토 완료: ‘계획대로 착수’. 실행은 첫 기반 독립 검토의 중요 문제 해결 후 시작한다.

2026-10-16 합류 checkpoint: 실제 DB 213 passed·설치/Node6·환경 격리·브라우저 로그인/동의/복수 업로드/HEIC/수동순서/실패삭제/PUT 응답유실/계정 격리를 확인했다. 독립 검토 Important3·Minor1은 별도 수정 Task로 진행 중이며 해당 문제 해결 전 완료 처리하거나 다음 묶음 구현을 시작하지 않는다. 상세: docs/로컬업로드-독립검토.md.

최종 총괄 판정: Important3·Minor1의 원인에 대응하는 수정과 실제 DB 회귀가 완료됐다. 실제 DB 224 passed, Node11·tsc/Vite·재현 설치 통과. 원래 독립 검토의 Not ready는 수정 전 HEAD 판정이며 이 checkpoint는 수정 후 근거로 로컬 연동 완료로 판정한다. 실제 외부 연동·HDR/실기기 합격으로 확대하지 않는다. 수정 작업자 보고서는 별도 보존한다.
