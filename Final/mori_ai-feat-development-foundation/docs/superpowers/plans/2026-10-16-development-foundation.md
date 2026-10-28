# 사진첩 첫 개발 묶음 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Orca 감독형 Task/worker-start로 작업자를 배정하며 각 작업자는 자신의 범위만 실행한다. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외부 서비스 호출 없이 독립 web/worker/DB 기반을 만들고, HEIF/WebP 및 PostgreSQL 작업 복구의 기술 위험을 먼저 검증한다.

**Architecture:** FastAPI가 React SPA와 API를 같은 origin으로 제공하고 PostgreSQL이 실행 상태를 소유한다. 별도 worker는 DB polling을 사용하며 생성 task와 비생성 background job을 구분한다. 미디어 처리와 DB/worker 검증은 공통 기반 완료 후 서로 다른 파일 범위에서 병렬 실행한다.

**Tech Stack:** Node 24, React 19, TypeScript 5.9, Vite 7, React Router 7, TanStack Query 5; Python 3.12 Bookworm/Linux amd64, FastAPI/Pydantic 2, SQLAlchemy 2/asyncpg/Alembic, PostgreSQL 17, Pillow/pillow-heif. 정확한 patch는 V01에서 resolve·lock한다.

**Spec:** [설계](../../설계.md) 2~5절, [공통계약 v1.3](../../공통계약-v1.md) 2·3·5절, [검증계획](../../검증계획.md) V01~V04·V09. 전체 사진첩 기능 구현은 이 첫 묶음의 완료 범위가 아니다.

## Global Constraints

- 외부 broker·Redis·Celery·별도 frontend 서버를 배포 구성에 추가하지 않는다.
- DB는 PostgreSQL 17로 검증하며 SQLite 통과로 대체하지 않는다.
- 입력 사진은 1~50장, 장당 20MiB·전체 300MiB·4천만 픽셀 기준을 유지한다.
- HEIF/HEIC 필수·WebP 정규화·원본 보존·크롭 금지·정확한 3:4 분기를 유지한다.
- API 키·운영 DB·bucket·사용자 사진을 기존 서비스에서 가져오지 않는다. 이번 묶음의 AI는 가짜 adapter만 사용한다.
- 승인된 전체 순서는 기술 기준→계약 보완→기반→병렬 위험 검증→기능 연동·통합이다. 외부 배포·유료 호출은 준비값 검토 후 실행한다.
- 공유 checkout의 commit·manifest·lock·Compose·migration은 지정 소유자만 수정한다.

## Review Focus

- SPA fallback이 잘못된 API·정적 파일 요청을 성공 HTML로 바꾸지 않는가: Task 1 경로 테스트.
- 두 작업 공간이 같은 DB·volume을 공유하지 않는가: Task 1 Compose 이름·volume 검증.
- EXIF 반전·투명도·HDR 입력이 회전 중복·alpha 손실·부정확 색상으로 통과하지 않는가: Task 2 fixture별 검사와 수동 HDR 기록.
- timeout된 미디어 자식 프로세스가 worker heartbeat를 멈추지 않는가: Task 2 프로세스 격리 테스트.
- lease 만료가 이미 발송한 AI를 재호출하거나 stale 결과를 연결하지 않는가: Task 3 실제 DB·가짜 호출 계수 검증.

## 단계별 상태와 이후 범위

| 단계 | 이번 상태·완료 기준 |
|---|---|
| 1 기술 시작 기준 | 설계 2절 조합 채택. patch 호환성은 Task 1의 V01로 판정 |
| 2 계약 보완 | v1.3·샘플 반영. 문서·JSON 정합성 검증 후 기준 commit |
| 3 최소 기반 | Task 1, V01 성공·독립 web/worker/DB 실행 |
| 4 위험 병렬 검증 | Task 2와 Task 3을 동시 실행, V02/V03/V04/V09 결과·미확인 항목 기록 |
| 5 기능 연동·통합 | 위 결과 반영 후 UI·인증·업로드·생성·수정·뷰어 구현 묶음을 구체화. V05~V08/V10과 세 합류점으로 검증 |

5단계의 실제 연동에 필요한 사용자 준비값은 새 Google/Kakao OAuth 앱, R2 bucket/키, AI 계정·글귀 model·예산, 배포 plan·도메인, 권리 확보 BGM이다. 비밀값은 채팅·문서에 입력하지 않고 새 서비스의 로컬/배포 secret 설정으로 제공한다. 아직 해당 자원을 생성하거나 유료 호출하지 않는다.

## Task 1: 재현 가능한 개발 기반과 V01

**Owner:** 기반 담당 1명. manifest·lock·Compose·Makefile·bootstrap의 단독 편집자.

**Files:**
- Create: `.gitignore`, `.env.example`, `Makefile`, `compose.yaml`, `Dockerfile`, `.dockerignore`.
- Create: `backend/__init__.py`, `backend/main.py`, `backend/settings.py`, `backend/worker/__init__.py`, `backend/worker/__main__.py`, `backend/requirements.in`, `backend/requirements-dev.in`, `backend/requirements.lock`.
- Create: `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`.
- Create/Test: `backend/tests/test_web_boundary.py`, `scripts/verify-install.sh`, `scripts/verify-isolation.sh`.
- Modify: `README.md`에 실제 성공한 실행·검증 명령과 버전 기록.

**Interfaces:**
- Produces: `backend.main.create_app(static_dir: Path | None = None) -> FastAPI`, `GET /health` → 200 `{"status":"ok"}`. 사용자 API를 가짜 성공으로 구현하지 않는다.
- Produces: `backend.settings.Settings`의 `database_url`, `storage_mode`, `storage_root`, `worker_poll_seconds` 및 설정 검증. secret 기본값 없음.
- Produces: `python -m backend.worker`의 SIGTERM 처리·안전 종료 entrypoint. 실제 task 실행은 Task 3이 소유.
- Produces: `make up`, `make down`, `make verify-install`; Compose 기본 서비스 postgres/web/worker, 공유 local media volume.

- [x] **Step 1:** `test_health_ok`, `test_missing_api_is_404`, `test_missing_static_asset_is_404`, `test_spa_route_serves_index`를 작성한다. 없는 `/api/v1/*`·`/assets/*`는 HTML 200이 아니며 SPA `/albums`만 index를 반환하는 것을 확인한다.
- [x] **Step 2:** 최소 test 의존성을 설정하고 `pytest backend/tests/test_web_boundary.py -q`를 실행해 아직 없는 create_app 때문에 실패함을 확인한다.
- [x] **Step 3:** create_app·Settings·React 기본 shell과 worker entrypoint를 구현한다. shell에는 기반 준비 상태만 표시하며 로그인·생성 성공을 가장하지 않는다.
- [x] **Step 4:** Node 24/Python 3.12 Bookworm의 새 의존성만 resolve한다. Linux amd64에서 pip-tools로 hashes lock을 만들고 npm lock을 만든다. 기존 manifest를 복사하지 않는다.
- [x] **Step 5:** frontend build를 backend image로 복사하고 같은 origin으로 제공한다. Compose에는 하드코딩 container_name을 두지 않고 프로젝트 이름별 DB·media volume을 분리한다. healthcheck와 DB 준비 대기를 추가한다.
- [x] **Step 6:** `make verify-install`에서 clean image build·hash 기반 pip 설치·pip check·주요 import·npm ci·tsc/Vite build·web 경계 테스트를 수행한다. 실패 시 non-zero, 성공 시 버전·image digest를 출력한다.
- [x] **Step 7:** `scripts/verify-isolation.sh`로 임시 Compose project 2개를 실행해 DB 표식과 media 파일이 공유되지 않는지 확인한다. 검사 종료는 생성한 두 project만 정리한다.
- [x] **Step 8:** V01 결과와 실제 실행 명령을 README/검증계획에 기록한다. `git diff --check` 후 총괄이 명시 파일만 commit한다.

## Task 2: HEIF/WebP 미디어 경계와 V02/V09

**Depends:** Task 1. **Owner:** 미디어 담당. DB·migration·공통 lock 편집 금지. 필요한 새 의존성은 기반 담당에게 요청.

**Files:**
- Create: `backend/media/__init__.py`, `backend/media/contracts.py`, `backend/media/normalize.py`, `backend/media/process.py`.
- Create/Test: `backend/tests/media/test_normalize.py`, `backend/tests/media/test_process.py`, `tests/fixtures/media/manifest.json`, `scripts/verify-codecs.sh`, `scripts/verify-media-load.sh`.
- Modify: `docs/검증계획.md`의 담당 V02/V09 결과만. 총괄이 Makefile target 연결.

**Interfaces:**
- Produces: `normalize(source: bytes, filename: str) -> NormalizedImage`; 필드 `webp_bytes`, `thumbnail_bytes`, `width`, `height`, `input_is_3_4`, `captured_at_raw`, `captured_timezone`, `sha256`. domain 예외 `MediaValidationError(code: str)`.
- Produces: `normalize_in_process(source_path: Path, filename: str, timeout_seconds: int = 120) -> NormalizedImage`. 자식 프로세스 종료와 임시 파일 정리 책임을 소유한다.
- Consumes: 계약의 HEIF primary·방향·색상·날짜·WebP·최대 크기 규칙. storage/DB에 결과를 연결하지 않는다.

- [x] **Step 1:** 허용된 synthetic PNG/JPEG/WebP와 EXIF 방향 fixture의 manifest에 checksum·실크기·예상 방향·alpha·비율을 기록한다. 실제 iPhone HDR fixture는 사용 권한 확보 전 미실행으로 남긴다.
- [x] **Step 2:** 테스트 `test_rotated_3_4_sets_passthrough`, `test_nearly_3_4_is_not_passthrough`, `test_alpha_survives`, `test_source_bytes_unchanged`, `test_pixel_limit_rejected`, `test_corrupt_input_rejected`를 작성한다. 결과 RIFF/WEBP magic·MIME·정확한 비율·4천만 픽셀 경계도 검증한다.
- [x] **Step 3:** `pytest backend/tests/media/test_normalize.py -q` 실패를 확인한 후 공통계약 2.3의 순서로 최소 구현한다. 날짜 추출은 metadata 제거 전에, input_is_3_4는 방향 적용 후 원본 크기로 계산한다.
- [x] **Step 4:** `test_timeout_does_not_block_heartbeat`를 작성한다. 고의 지연된 자식은 timeout 후 종료되고 부모 async heartbeat는 계속 증가하며 임시 파일은 정리되어야 한다. 실패 확인 후 process 격리를 구현한다.
- [x] **Step 5:** 같은 Linux amd64 image에서 `make verify-codecs`와 `make verify-media-load`를 실행한다. 최대 크기 자료 50개를 동시 1개로 처리하고 RSS·OOM·시간·codec 버전을 기록한다. RSS는 서비스 한도의 80% 이하여야 한다.
- [x] **Step 6:** 실제 HEIC/HEIF·ICC/HDR/10bit 자료와 육안 기준이 없으면 V02 전체 성공으로 보고하지 않는다. 단순 8bit 변환을 HDR 합격으로 취급하지 않으며 추가 변환기 선택이 필요하면 근거와 실패 자료를 총괄에 보고한다.
- [x] **Step 7:** 담당 파일·검증 결과를 보고한다. 총괄 검토 후 명시 파일만 commit한다.

## Task 3: PostgreSQL 실행권·복구와 V03/V04

**Depends:** Task 1. **Owner:** 백엔드/worker 담당, 이 묶음의 migration 단독 편집자. media 파일·공통 lock 편집 금지.

**Files:**
- Create: `backend/database.py`, `backend/models.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/0001_workflow_foundation.py`.
- Create: `backend/generation/__init__.py`, `backend/generation/repository.py`, `backend/generation/resume_policy.py`, `backend/worker/jobs.py`, `backend/worker/runner.py`.
- Create/Test: `backend/tests/integration/test_claim_fence.py`, `backend/tests/integration/test_job_recovery.py`, `backend/tests/integration/test_resume.py`, `scripts/verify-db.sh`, `scripts/verify-worker.sh`.
- Modify: `backend/worker/__main__.py` (Task 1 완료 후 소유권 이전), `docs/검증계획.md`의 V03/V04 결과. Makefile 연결은 총괄.

**Interfaces:**
- Produces: `backend.database.session_factory` (`async_sessionmaker[AsyncSession]`), 호출/heartbeat마다 별도 session.
- Produces: `claim_task(session: AsyncSession, now: datetime, lease_seconds: int) -> TaskClaim | None`; TaskClaim은 `task_id`, `fence_version`, `lease_until`을 가진다. 짧은 transaction·SKIP LOCKED·fence 증가.
- Produces: `settle_task(session: AsyncSession, task_id: UUID, fence: int, outcome: str, now: datetime) -> bool`; stale fence·deleted album이면 False, 공개 결과 연결 금지.
- Produces: `eligible_resume_tasks(tasks: Sequence[ResumeTask], has_unknown: bool) -> list[UUID]`; ResumeTask 필드는 `id`, `status`, `safe_to_retry`, `requires_ai_call`, `has_persisted_input`. v1.3 조건의 failed만 반환.
- Produces: `reserve_upload_validation(session, upload_id: UUID, now: datetime) -> str`; complete 기한과 같은 시각부터 expired, validating과 unique job은 원자 저장.
- Consumes: 계약 v1.3 스키마. 이 묶음은 API 인증·업로드·생성 전체 endpoint 구현을 포함하지 않는다.

- [x] **Step 1:** 실제 PostgreSQL 17의 새 테스트 DB에 최소 users/albums/media/upload/run/task/attempt/outbox/background_jobs 모델과 migration을 작성한다. 나머지 공개 기능은 후속 migration으로 추가하며 기존 migration을 복사하지 않는다.
- [x] **Step 2:** 두 DB 연결의 `test_only_one_claim_wins`, `test_stale_fence_cannot_settle`, `test_deleted_album_rejects_late_result`를 작성하고 미구현 repository로 실패함을 확인한다. 이후 claim/settle을 구현한다.
- [x] **Step 3:** `test_complete_and_validation_job_are_atomic`, `test_duplicate_complete_has_one_job`, `test_complete_at_deadline_expires`, `test_validating_survives_put_expiry`를 작성한다. 실패 확인 후 원자 접수·unique job·만료 조건을 구현한다.
- [x] **Step 4:** `test_sent_attempt_lease_expiry_is_unknown_without_second_call`, `test_unsent_attempt_can_requeue`, `test_saved_result_recovers_without_ai`, `test_outbox_replay_has_one_cleanup_job`를 작성한다. 가짜 adapter에 호출 계수와 barrier를 넣어 강제 종료·재시작을 재현하고 최소 runner/scanner를 구현한다.
- [x] **Step 5:** `test_unknown_allows_only_persisted_local_retry`, `test_unknown_blocks_ai_retry`, `test_no_unknown_allows_safe_failed_retry`를 작성한다. 실패 확인 후 resume 정책과 action_required 유지 조건을 구현한다.
- [x] **Step 6:** `make verify-db`, `make verify-worker`를 실행한다. 실제 DB 2연결·재시작·호출 계수·fence를 근거로 V03/V04 결과를 기록한다. SQLite·프로세스 내 가짜 상태만으로 통과하지 않는다.
- [x] **Step 7:** migration 재적용 재현과 `git diff --check` 후 담당 파일·결과·제약을 보고한다. 총괄 검토 후 명시 파일만 commit한다.

## 통합·검토와 다음 계획의 입력

- [x] Task 1 완료 후에만 Task 2/3을 Orca의 서로 다른 Task로 동시에 시작한다. 공유 checkout에서 파일 범위가 겹치면 먼저 소유권을 조정하고 필요 시 기준 커밋에서 worktree로 격리한다.
- [x] 총괄은 두 작업자의 보고·실제 파일·검증 결과를 확인하고 작업자를 재사용하거나 worker-release한다.
- [x] V01~V04/V09의 성공·실패·미실행을 분리해 기록한다. HEIC/HDR 자료 부재는 제품 요구 제거의 근거가 아니다.
- [ ] 이후 기능 묶음은 계약 타입·샘플 UI와 인증/업로드/API를 먼저 연결하고, 실제 AI·R2→검토/완성/뷰어 순으로 구현한다. 전체 서비스 완료는 V05~V08/V10·50장·실기기·세 합류점의 검증 후 판정한다.

## 계획 자체 점검

- 이 첫 묶음의 spec 범위인 설치·실행 경계·codec·실행권·복구 요구는 Task 1~3에 배정했다. 전체 기능 API와 UI·외부 연동은 범위 밖임을 명시했다.
- media와 repository는 서로의 내부 타입을 import하지 않으며 통합은 후속 application 작업이 담당한다.
- 코드 경로·소유권·공통 값·명령·합격 조건을 명시했다. 실행 전 사용자 계획 검토가 필요하며 현재 checkbox는 실행 완료를 뜻하지 않는다.

첫 기반 최종 통합(2026-10-16): f89f02a에서 리뷰 I1~I4/M1~M2 수정 완료, 실제 DB 전체 163 passed·clean 설치 102 passed/DB 61 skipped·media 70 passed·합성 50장·두 환경 격리 통과. V02 부분/V09 합성 한계는 유지한다. 다음 로컬 연동 계획은 별도로 사용자 승인됐다.
