# 로컬 가짜 AI 생성·수정·뷰어 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자가 선택한 Orca 감독형 실행을 유지하고 총괄이 Task·Dispatch·편집 소유권·검증·통합을 관리한다.

**Goal:** 검증된 업로드에서 가짜 AI 생성→결과 확인→글귀 저장→사진첩 완성→소유자 뷰어까지 로컬에서 확인한다.

**Architecture:** 기존 generation_tasks/attempts 실행권·발송 경계·ResultStore·비공개 LocalStorage를 사용한다. API는 입력 스냅샷을 고정하고 worker가 stage별 보존 결과를 연결하며 전체 완료 집계는 domain/repository의 한 transaction에서 수행한다. 가짜 adapter는 명시적 로컬 설정에서만 설치한다.

**Tech Stack:** 현재 Python/FastAPI/PostgreSQL·Pillow/WebP·React/TypeScript. 신규 SDK/의존성 설치와 외부 연결 없음.

**Spec:** 기능요구명세서.md, docs/공통계약-v1.md 2~5절·샘플, docs/설계.md, 로컬 업로드 연동 계획·검증 결과. 사용자가 로컬 업로드 다음에 가짜 AI·수정·뷰어를 연결하는 순서를 승인했다.

## Global Constraints

- 선행 로컬 업로드 묶음의 브라우저 합류 검증과 독립 리뷰의 Critical/Important 해결 후 착수한다.
- DEV_AI_ENABLED 기본 false, APP_ENV=local에서만 허용. production과 함께 켜면 설정 실패다. UI의 진행/검토/뷰어에 ‘개발용 가짜 AI 결과’를 표시한다.
- 실제 Google/Kakao/R2/OpenAI·유료 호출·배포·공개 공유 없음. 운영 이미지 모델 GPT Image 2 결정은 유지하며 가짜 모델을 실제 제공자 모델로 기록하지 않는다.
- 가짜 caption은 고정된 정상 한 문장이다. 가짜 이미지는 원본을 자르거나 늘이지 않고 3:4 canvas에 배치한 테스트 파생본이며 실제 AI의 자연스러운 확장 품질을 증명하지 않는다.
- 원본이 정확히 세로 3:4이면 image_transform은 succeeded+passthrough이며 이미지 가짜 adapter 호출도 0회다. 정규화·caption·optimize는 수행한다.
- 1~50장·파일20MiB·총300MiB·40MP·NFC code point 80자와 v1.3 상태/DTO/오류/버전/멱등 규칙 유지. 새로운 공개 enum/endpoint/재생성 기능을 추가하지 않는다.
- 미확인 발송은 unknown, 원래 응답 회수만 허용하며 자동 새 요청 금지. mock 성공은 실제 AI·OAuth·R2 성공이 아니다.
- 로컬 fake 실행은 현재 단일 worker 구성에서 시작하고 CPU 파일 처리는 비동기 subprocess로 격리한다. 처리 병렬 수를 늘리거나 배포 용량 합격을 주장하지 않는다. 이미지2/글귀4 등 설계 상한은 초과하지 않는다.
- 모델/migration·공통 설정·worker bootstrap·의존성/lock은 지정한 단일 편집자가 소유한다. 기존 moriai는 읽기 전용이며 이번 묶음에서는 이식하지 않는다.

## Review Focus

- 두 사진첩/두 API 연결의 동시 생성: 사용자별 미완료 run 1개와 key replay를 원자 보장. Task1 실제 DB 테스트.
- 마지막 task 완료·unknown 원래 결과 회수·삭제 경합: 모든 결과/글귀 commit 뒤만 review_ready, 삭제 뒤 연결 금지. Task2 실제 DB 테스트.
- image 성공 뒤 optimize 파일 저장 실패: 보존 결과만 다시 사용하고 image adapter 재호출 0. Task2 강제 종료·재시작 검사.
- emoji/조합 한글/빈 사용자 글귀·다른 페이지의 동시 저장: NFC code point 80과 page.version 비교, 미저장 입력 보존. Task3/4 검사.
- 뷰어 URL 만료·다른 사용자 전환·모바일 화면 회전: 재발급/격리/현재 페이지 유지, contain으로 사진 내용 보존. Task3/4 실제 브라우저 검사.

## Task 1: 생성 접수·진행·재개 HTTP

**Files:** Create backend/generation/{service,routes,views}.py, backend/tests/integration/test_generation_http.py. Modify backend/main.py router 등록, backend/settings.py·compose.yaml·.env.example의 가짜 AI opt-in 설정. 추가 schema가 필요하면 총괄 소유의 0003 이후 새 migration으로 분리하고 0001/0002는 수정하지 않는다.

**Interfaces:** POST /api/v1/albums/{id}/generation, GET /generation, POST /generation/resume. create_generation(session, owner_id, album_id, expected_version, key, request_hash, settings) → (status, data), generation_view(session, owner_id, album_id, run_id=None) → GenerationView. 기존 idempotency helper를 사용하고 caller가 transaction을 소유한다.

- [x] 실제 DB HTTP RED: 최신 동의/전부 ready/수량·용량/버전, 같은 key replay가 버전 검사보다 우선, 두 album 동시 요청 중 사용자별 미완료 run 1개, action_required도 점유, 성공 album의 새 생성 거부.
- [x] User→Album→Run→Task lock 순서로 immutable input/config snapshot·run/task/outbox·album processing을 원자 저장한다. 각 page의 normalized asset ID·checksum·순서·3:4 판정, fake provider/model·prompt 버전·인코딩·재시도 설정을 보존한다.
- [x] GenerationView는 완료→unknown→failed→pending 우선순위로 페이지를 상호 배타 집계한다. task.retryable/can_resume은 기존 eligible_resume_tasks와 일치하며 숨겨진 화면/terminal 상태 polling 정책을 유지한다.
- [x] resume의 owner/동의/version/key·unknown 혼합 조건을 테스트하고 기존 resume_failed_tasks의 자체 transaction 호출을 유지하면서 caller-owned helper를 분리해 HTTP transaction에 연결한다. 성공 task는 유지하며 unknown 새 호출을 예약하지 않는다.
- [x] 전용·전체 실제 DB 회귀 통과, 공개 계약 변경 여부/미실행 범위 보고 후 총괄 commit.

## Task 2: 로컬 fake adapter·실행·전체 완료 집계

**Depends:** Task1. **Files:** Create backend/generation/fake_adapter.py, backend/generation/completion.py, backend/media/fake_transform.py, backend/tests/integration/test_generation_pipeline.py. Modify backend/worker/{runner,__main__}.py, backend/generation/repository.py와 backend/storage/local.py·backend/uploads/service.py·validation.py의 canonical key/cleanup 연결은 단독 소유권을 이전받아 편집한다. 기존 초안 thumbnail과 결과 thumbnail의 immutable bytes 충돌을 피하고 공개 계약의 transform_output role를 저장할 수 있게 한다. Task3과 동시 변경하지 않는다.

**Interfaces:** fake adapter의 execute(attempt_id, stage) → {caption:string} 또는 {asset_id:UUID string}. 입력은 run.input_snapshot의 같은 normalized 원본이다. optimize는 보존 transform_output/normalized로 result·thumbnail을 영속화하고 기존 ResultStore envelope와 stage 검증을 사용한다. recompute_completion(session: AsyncSession, album: Album, run: Run) → None은 task settlement와 같은 transaction에서 호출한다.

- [x] RED: portrait passthrough 가짜 image 호출 0·caption/optimize 수행, landscape fake 3:4 crop/distortion 없음·WebP 결과, caption/input checksum 일치·source bytes 유지, 처리 중 API/heartbeat 지속.
- [x] 가짜 caption ‘함께한 순간이 오래도록 마음에 남아요.’와 async fake_transform(normalized_path: Path, *, max_edge: int = 4096) → bytes를 구현한다. 파생본은 최대 긴 변 4096px·정확한 3:4이며 축소가 필요하면 contain 방식으로 전체 사진을 보존하고 남는 canvas는 #ead8bb로 채운다. 각 실제 asset bytes checksum·owner/album/page/role/ready를 검증하고 source/normalized는 승격하거나 지우지 않는다.
- [x] ai_caption과 caption_text 초기 저장, 세 task succeeded·result/thumbnail ready 조건을 같은 transaction에서 확인하고 마지막 완료 시 run succeeded/album review_ready·시각·version을 변경한다. 사용자 수정이나 기존 성공 결과를 덮어쓰지 않는다.
- [x] RED→GREEN: sent 강제 종료 unknown/추가 호출0, 저장 뒤 crash 원래 결과 replay, optimize 저장 실패의 안전한 로컬 재개, stale fence·삭제·invalid 출력의 실패 수렴, unknown 원래 결과 회수 뒤 전체 완료.
- [x] 실제 DB 전체와 작은 synthetic 1/복수/50장 pipeline을 검증한다. CPU·OOM·시간은 측정 조건을 기록하며 실제 AI 지연·최악 HEIC/HDR 부하로 확대하지 않는다. 총괄 commit.

## Task 3: 글귀 저장·완성·소유자 뷰어 API

**Depends:** Task2. **Files:** Create backend/albums/editing.py, backend/albums/viewer.py, backend/tests/integration/test_review_viewer_http.py. Modify backend/albums/routes.py·service.py와 필요한 미디어 발급 연결을 단독 소유권으로 배정한다.

**Interfaces:** PATCH /albums/{id}/pages/{page_id}/caption, POST /albums/{id}/publish, GET /albums/{id}/viewer. save_caption(session, owner_id, album_id, page_id, expected_version, caption_text) → {page,album_version}; publish_album(session: AsyncSession, owner_id: UUID, album_id: UUID, expected_version: int) → {album}; get_viewer(session: AsyncSession, owner_id: UUID, album_id: UUID) → Viewer. 기존 session/CSRF/owner/no-store/envelope를 사용한다.

- [x] 실제 DB RED: review_ready/published에서만 수정, 빈 문자열 허용·NFC80 허용81 거부, page.version 충돌 details, 다른 페이지 저장 독립성, AI 호출0·ai_caption 보존.
- [x] 저장·publish를 구현하고 동시 마지막 저장/완성·응답 유실 재전송·이미 published 동일 version의 응답을 확인한다. 전체 결과 ready를 재검사하며 deleted/다른 owner는404다.
- [x] viewer는 published만 허용하고 순서·WebP·caption을 반환한다. 최초 첫 장/다음 장만 media_access를 발급하며 나머지는 기존 media-access를 사용한다. source/AI 중간 파일 접근을 금지한다.
- [x] music=null은 권리 확보 BGM 미준비 상태로 유지한다. BGM 기능 합격을 주장하지 않는다. URL 만료·삭제·다른 사용자 접근·전체 DB 회귀 후 총괄 commit.

## Task 4: 진행·검토·뷰어 화면과 합류 검증

**Depends:** Task1의 공개 인터페이스가 고정되면 frontend만 병렬 진행 가능. Task2/3 완료 뒤 실제 합류한다.

**Files:** Create frontend/src/features/generation/GenerationProgress.tsx, frontend/src/features/review/ReviewEditor.tsx, frontend/src/features/viewer/AlbumViewer.tsx. Modify frontend/src/api/{types,client}.ts, features/albums/AlbumEditor.tsx·Bookshelf.tsx, App.tsx·styles.css. backend/lock 편집 금지.

- [x] 서버 ready·동의 조건 뒤 실제 generation 접수와 polling을 연결한다. page별 task/완료 수를 사용하고 fake 진행률·시간은 만들지 않는다. 실패/unknown 안내·허용 resume·삭제를 제공한다.
- [x] 결과 화면에 페이지별 명시적 저장을 연결한다. NFC code point 수/빈 문자열/80자·409 비교·미저장 이탈·완성 전 저장 또는 버리기·응답 실패 입력 보존을 구현한다.
- [x] published 소유자 뷰어: 3:4 contain, 본문, 이전/다음·키보드·터치·페이지 표시·reduced motion, 회전/리사이즈 현재 page 유지. 만료 URL은 재발급하고 logout 시 이미지/query cache를 지운다.
- [x] ‘개발용 가짜 AI 결과’ 표시와 BGM 미준비를 실제 상태로 표시한다. 생성/실제 AI/음악/모바일 합격을 서로 대신하지 않는다.
- [x] tsc/Vite·전체 DB·실제 Orca 브라우저에서 upload→fake generation→수정→publish→viewer→logout/다른 사용자→삭제를 검증한다. 독립 전체 리뷰의 중요 문제 처리 후 보고·총괄 commit.

## 자체 점검과 완료 경계

접수/진행/재개(Task1), 보존 실행/집계(Task2), 수정/완성/뷰어 API(Task3), 화면(Task4)에 공개 계약과 다섯 Review Focus를 배정했다. worker 공통 파일의 동시 소유자는 한 명이며 frontend만 독립 병렬화한다. 이 묶음은 외부 계정 준비 전에 검증 가능한 로컬 전체 흐름을 만든다. 실제 OAuth·R2·AI 모델 식별자/과금·HDR/P3 tone mapping·권리 확보 BGM·실제 모바일/배포는 별도 남은 검증이다. 2026-10-16 사용자 검토 완료: ‘계획대로 이어서 진행’. 선행 업로드 묶음의 검증과 중요 리뷰 문제 해결 후 실행한다.

2026-10-16 최종 독립 검토에서 unknown 원래 응답 회수 뒤 미발송 AI 단계의 재개 고착을 확인했다. 기존 failed-only 명시 resume 계약을 유지하며 안전한 미발송 queued/retry_wait 단계를 재개 가능한 실행 보류로 분류한다. 아직 unknown·실행 중·발송 미확정 단계는 제외하고 성공 작업/원래 attempt를 재발송하지 않는다. 별도50장검사실패는lease/maintenance와상태dump로원인을확인하며, 삭제응답유실안내도서버404재확인으로보완한다. 새endpoint/enum/의존성/비용범위확대없음.

최종 완료: 2026-10-16. Task 1~4 구현·합류 및 중요 리뷰 수정 완료. 실제 DB 307개, Node 36개, 재현 빌드 통과. 상세 검증·실기기 및 외부 연동 미실행 경계는 [통합 검증 결과](../../로컬생성화면-검증결과.md)를 따른다. 체크된 항목의 키보드/터치/리사이즈는 브라우저 이벤트 검사이며 물리 모바일 검사 완료를 의미하지 않는다.
