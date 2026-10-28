# 서비스용 사진 전처리 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement owned tasks with tests. User approved sequential execution and independent parallel implementation on 2026-10-18; no repeated execution gate.

**Goal:** 선택적 브라우저 전처리, 메모리 제한 내 서버 정규화, source 파일 없는 생성·복구를 구현한다.
**Architecture:** 업로드 전에 JPEG/PNG의 안전한 입력만 순차 변환한다. 서버는 모든 파일을 검증하고 정규화 인코딩한다. 검증 완료 normalized는 이후 생성·재시도에서 재사용한다. 원본은 검증 중 임시 입력이며 normalized 확보 후 삭제 가능하다. 기존 DTO는 선택적 필드로 확장하고 기존 예약 snapshot은 호환한다.
**Tech Stack:** React/TypeScript browser Canvas, FastAPI/Pydantic, Pillow, PostgreSQL, existing local/R2 storage.
**Spec:** docs/공통계약-v1.md v1.6, latest user instructions.

## Global Constraints
- QA/production DB, media, env and Lightsail runtime are untouched. No paid AI calls, no dependency installation or lock changes by workers, no commits by workers.
- Upload limits remain 20MiB/file, 40MP original, 50 files, 300MiB/album; client processing is optional and cannot bypass server actual file validation.
- Preserve orientation, alpha, captured date, lastModified, pre-resize exact portrait 3:4 decision. Never crop/stretch/upscale.
- New normalization defaults: lossy WebP quality90, maxedge4096, maxbytes20MiB. Legacy explicit lossless snapshots remain executable.
- Eligible browser JPEG/PNG only, <=12MP initially to bound memory; unsafe metadata/color/HDR/unsupported decode/encode fallback unchanged. Actual WebP MIME and smaller output required. Sequential processing, abort cleanup, same prepared File retained through reservation and retry.

## Interfaces / Ownership
- Optional reservation file field `preprocessing`: `{version:1, original_width:int, original_height:int, captured_at_raw:string|null, captured_timezone:string|null}`. Width/height are original orientation-corrected pixels, <=40MP. Only sent on actual WebP conversion. Original exact 3:4 uses these dimensions; server validates dimensions compatible with resized aspect ratio/rounding and actual WebP, no upscale. Metadata is an untrusted sorting/branch hint, never validation authority.
- Store preprocessing in existing Upload.validation_config JSON; no migration. Server normalize gets only media configuration, not arbitrary frontend claims. Validation worker checks metadata against actual normalized dimensions, applies dates/branch after successful decode.
- Frontend worker owns frontend/src/features/uploads/**, frontend/src/api/types.ts, frontend/tests/*preprocess* only. Creates preparation helper and integrates useUploads. No deps/lock changes.
- Media worker owns backend/media/**, backend/settings.py, backend/tests/media/**, backend/tests/test_media_settings.py, .env.example normalization fields only. Adds NORMALIZED_WEBP_QUALITY config and process allowlist; preserves old lossless=true option. Tests memory, uploaded WebP payload removal and legacy byte compatibility.
- Backend worker owns backend/uploads/**, backend/generation/service.py, backend/tests/integration/*upload*, backend/tests/integration/test_generation_http.py and dedicated source-retirement tests. Adds config snapshot quality, validates new optional metadata, retires source safely and removes generation file dependency. No edits to media/settings/frontend/docs.
- Coordinator owns docs/contracts/examples, build test integration, final review/fixes after worker handoff.

## Review Focus
- Browser EXIF orientation/date, transparent PNG, unsupported encode returning PNG, abort and retry use identical prepared bytes.
- Forged metadata, near-3:4 rounding, >40MP dimensions, mismatched resized aspect and actual non-WebP rejected.
- 40MP input normalization under512MiB child limit; low-memory reject remains controlled for unsupported paths.
- Source removal after ready must preserve complete replay, generation, recovery and legacy uploads; late PUT after deletion must be swept.
- Existing explicit lossless snapshots and data remain usable; no bulk deletion at deployment startup.

## Tasks
### 1. Parallel frontend preparation
- [x] Add failing tests for eligible conversion/fallback, metadata extraction, rounding, sequential/abort/retry stability.
- [x] Implement helper and useUploads preparation before reservation; preserve original selection UI and lastModified.
- [x] Run TypeScript/build and frontend regression tests.
### 2. Parallel codec memory/quality
- [x] Add tests for lossy default, explicit lossless legacy, uploaded WebP re-encoding/payload removal, metadata stripping, original 3:4 and decode limits.
- [x] Reduce full-resolution copies and shrink early where color/orientation semantics allow; keep memory/timeout guards.
- [x] Run media tests and high-resolution memory measurement.
### 3. Backend metadata and source lifetime
- [x] Add negative metadata tests and source-free generation/replay/deletion tests.
- [x] Implement optional input validation/snapshot and source cleanup after durable normalized commit. Preserve accounting in Upload rather than source file existence.
- [x] Run isolated database integration tests.
### 4. Integration/review
- [x] Update contract/examples/config and verify no edits conflict with deployment session.
- [x] Run full frontend, media and affected backend integration; build runtime; measure synthetic high-resolution inputs under the same resource limits, no paid APIs.
- [x] Independent review, fix findings, document results and limits (actual mobile/external post-deploy validation separate).


## 독립 검토 후 보완
- [x] 이전 snapshot은 NORMALIZATION_VERSION=1의 동결된 기존 변환기로 실행하여 DB commit 전 생성된 불변 파일과 byte 일치를 유지한다. 새 예약은 version2다.
- [x] 업로드 WebP도 decoder가 무시하는 payload가 남지 않도록 서버에서 한 번 재인코딩한다. 무검증 bytes 채택 최적화는 제거한다. 이는 추가 손실 인코딩과 처리 시간이 드는 명시적 절충이며, 검증된 normalized의 생성·재시도 재사용은 유지한다.
- [x] 동의 기본 버전을 media-2026-10-18로 갱신하고 기존 배포 env의 명시적 버전도 업데이트하도록 인계한다. 기존 동의 이력은 보존한다.

## 완료 기록

구현·로컬 통합 검증·독립 재검토 완료. [검증 보고서](../../미디어-전처리-검증.md)에 결과와 한계를 기록했다. 운영 배포와 배포 후 모바일 실측은 별도 단계다.
