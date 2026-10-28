# PostgreSQL 실행권·worker 복구 검증 결과

- 일자: 2026-10-16, Task 3 (`task_829aeaabc996`, Dispatch `ctx_783c84b97339`).
- 기준: 승인된 개발 기반 계획 Task 3 / Global Constraints / Review Focus, 공통계약 v1.3, 설계 4·6절.
- 코드 출처: 이번 저장소에서 신규 작성. 기존 `moriai` 코드·migration·환경·DB·사진·키를 복사하거나 연결하지 않았다.
- 공개 계약 변경: 없음. attempt의 fence/result key/checksum과 task의 안전 재시도·로컬 입력 플래그는 내부 구현 필드다.

## 검증 환경과 실행

기존 Task 1의 `mori-ai:verify-tests` image와 Compose의 `postgres:17-bookworm`을 사용했다. 호스트 패키지 설치·lock 변경 없이 Linux amd64 컨테이너에서 실행했다. Python **3.12.15**, SQLAlchemy **2.1.4**, asyncpg **0.32.0**, Alembic **1.20.0**, pytest **9.1.1**, pytest-asyncio **1.4.0**, x86_64/glibc 2.36 환경이다. DB 실제 응답은 **PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2)**다. 실행마다 `mori-workflow-<timestamp>-<pid>`라는 독립 Compose project/network/volume과 `mori_workflow_test` DB를 만들고, EXIT trap은 그 project의 자원만 제거한다. `.env`를 읽지 않고 검증 전용 임시 비밀번호를 생성한다. 테스트는 DB 이름과 server_version_num을 확인한 뒤 임시 데이터만 초기화한다.

```bash
make verify-db
make verify-worker
bash scripts/verify-db.sh backend/tests
bash -n scripts/verify-db.sh scripts/verify-worker.sh
git diff --check
```

각 DB 명령은 migration `upgrade head → downgrade base → upgrade head → alembic check`를 먼저 실행한다. ORM과 frozen migration 정합성은 `No new upgrade operations detected.`로 확인했다. 기본 image가 없으면 Task 1의 verify-install을 먼저 실행해야 하며, 별도 image는 `MORI_VERIFY_TEST_IMAGE`로 지정한다. Makefile 연결은 총괄 소유이며 이 작업자는 수정하지 않았다.

| 검증 | 결과 |
|---|---|
| `make verify-db` | **26 passed**, 12.55초, exit 0 |
| `make verify-worker` | **14 passed**, 12.39초, exit 0 |
| `bash scripts/verify-db.sh backend/tests` | **93 passed**, 19.05초, exit 0, deprecation 경고 1개 |
| migration 재적용·metadata 비교 | 성공 |
| shell 문법·diff 공백 검사 | 성공 |

## 테스트 목록과 근거

### 실행권 / V03 (8개)

- `test_only_one_claim_wins`: 실제 두 AsyncSession과 서로 다른 `pg_backend_pid()` 연결의 동시 claim 중 하나만 승리, fence=1.
- `test_claim_skips_locked_task_without_waiting`: 첫 연결이 row lock을 유지하는 동안 두 번째 연결은 1초 안에 None, 해제 후 claim 가능.
- `test_stale_fence_cannot_settle`: 유효한 늦은 글귀가 있어도 이전 fence는 완료 불가.
- `test_deleted_album_rejects_late_result`: 삭제 상태의 album은 유효한 늦은 글귀를 공개 페이지에 연결하지 않음.
- `test_expired_lease_cannot_settle`: lease와 같은 시각부터 결과 연결 불가.
- `test_optimize_waits_for_image_success`: image_transform 선행 성공 없는 optimize claim 차단.
- `test_action_required_blocks_new_ai_claim`: action_required에서는 새 AI task claim 차단.
- `test_success_requires_persisted_output_and_is_terminal`: 결과 없는 성공 차단, 성공 후 재완료·실패 전이 및 글귀 덮어쓰기 차단.

### complete / validation job (4개)

- `test_complete_and_validation_job_are_atomic`: 실제 DB CHECK 오류를 job insert에 주입하면 validating 전이도 rollback; 정상 재실행은 둘 다 저장.
- `test_duplicate_complete_has_one_job`: 두 연결 동시 complete와 반복 complete는 unique job 1개, succeeded job도 재실행하지 않음.
- `test_complete_at_deadline_expires`: 최초 complete가 예약 기한과 같으면 expired, job 없음.
- `test_validating_survives_put_expiry`: validating 진입 후 2일 경과해도 같은 상태/job 유지.

### worker 복구 / V04 (10개)

- `test_sent_attempt_lease_expiry_is_unknown_without_second_call`: 가짜 AI의 fsync 호출 계수와 barrier 후 worker 자식 프로세스를 SIGKILL, 새 자식 프로세스로 재시작. unknown/action_required·정리 아닌 원래 attempt 확인 job 1개 유지, 원래 1회 외 추가 AI 호출 0, 반복 scanner의 album version 중복 증가 없음.
- `test_unsent_attempt_can_requeue`: prepared/not_sent barrier에서 SIGKILL; 재대기 후 새 프로세스의 실행으로 성공, 총 호출 1회.
- `test_saved_result_recovers_without_ai`: deterministic 결과 파일 fsync 후 DB 결과 기록 전 SIGKILL; 새 프로세스가 보존 파일로 공개 글귀와 succeeded를 복구, 추가 AI 호출 0.
- `test_outbox_replay_has_one_cleanup_job`: 중복 이벤트·두 연결 dispatcher·published_at 초기화 재전달에도 cleanup_album job 1개.
- `test_heartbeat_uses_independent_session_while_adapter_waits`: adapter barrier 대기 중 별도 DB 연결로 lease 증가 관찰, 동시에 album row lock 획득 가능. 외부 대기 동안 실행 transaction lock 없음.
- `test_job_lease_recovery_rejects_old_fence`: 두 연결의 validation job claim 1승, 만료 재예약은 fence 증가, 이전 worker 완료 차단.
- `test_saved_result_checksum_mismatch_stays_unknown`: 손상된 결과 envelope는 연결하지 않고 unknown 유지, 추가 호출 없음.
- `test_worker_entrypoint_sigterm`: 실제 `python -m backend.worker` 프로세스가 SIGTERM에 exit 0으로 안전 종료.
- `test_received_caption_in_db_recovers_without_file_or_ai`: attempt의 received 글귀가 DB에 보존되면 파일 없이 복구.
- `test_unsent_recovery_stops_at_attempt_budget`: 기본 최대 3회 소진 시 failed/action_required, 무한 재대기 차단.

### resume (4개)

- `test_unknown_allows_only_persisted_local_retry`
- `test_unknown_blocks_ai_retry`
- `test_no_unknown_allows_safe_failed_retry`
- `test_mixed_resume_keeps_action_required`: DB에서도 로컬 failed만 queued, AI failed·unknown 유지, album/run=action_required 유지.

## RED→GREEN 및 발견 사항

1. 초기 실행권 6개, complete 4개, 복구/resume 9개는 각각 미구현 repository/jobs/runner/resume_policy로 실제 DB에서 실패한 뒤 구현했다.
2. 추가 검토 테스트가 결과 없는 task의 succeeded 허용, background job finish fence 부재를 드러냈고 수정했다.
3. received caption이 DB에 있는데 파일만 조회하던 복구와 not_sent 시도 횟수 무제한 재대기가 RED였다. DB caption fallback과 기본 최대 3회 상한으로 수정했다.
4. unknown 전이의 album.version이 1에 머무르는 RED를 확인했다. 공통 상태 전이 함수가 action_required 변경과 version 증가를 같은 transaction에서 수행하고 반복 scanner는 증가시키지 않도록 수정했다.
5. 전체 회귀 최초 실행은 90 passed / 3 failed였다. `test_fixture_manifest`, `test_codec_check_failure_cannot_be_masked_by_pytest_success`, `test_codec_command_honors_explicit_test_image`는 검증 컨테이너에 tests/fixtures와 scripts가 mount되지 않아 실패했다. 이 실행 entrypoint에 해당 경로의 읽기 전용 mount를 추가해 재검증했다.
6. worker 검증 도중 같은 검증 스크립트를 수정한 한 실행은 테스트 14개가 통과했으나 shell parsing 오류를 출력했다. 해당 실행을 합격 근거에서 제외하고 스크립트를 고정한 뒤 명령을 재실행했다.
7. 샌드박스 내 Docker socket 및 Orca heartbeat 연결이 거부되었다. 지시에 따라 `require_escalated` 실행으로 해결했으며 앱 재시작은 하지 않았다.

## 구현 범위와 후속 migration

초기 migration은 **workflow foundation**이며 전체 공개 제품 schema라고 주장하지 않는다.

| 이번 구현 | 후속 migration·연동 |
|---|---|
| users의 식별자·표시명·감사시각, albums의 소유권·상태·버전·삭제 | auth_identities, sessions, consents, idempotency_records, album 정렬·cover/active_run·공개시각·updated_at |
| pages의 위치·selection_index unique·version·글귀·result 참조·제거 | source/normalized/thumbnail 참조, 촬영일·정렬 정보·사용자 글귀 편집시각·완전한 페이지 DTO |
| media_assets의 소유권/FK·storage_key unique·MIME·크기·checksum·상태 | 실제 storage/media adapter, 파생본 검증·checksum/config version 재사용·thumbnail 연결 |
| uploads의 예약 기한·상태·batch/client unique·원자 job 접수 | file_last_modified_at, 업로드 예약 API의 동의·수량·용량 검사, 실제 validate_upload handler |
| generation_runs의 snapshot·활성 run partial unique | 시작/종료시각, 사용자별 활성 run 제한·입력 스냅샷 확정·사용량/예산 검사·완료 집계 |
| generation_tasks / attempts의 unique·lease·fence·발송 경계·보존 응답 | 실제 AI port의 입력/출력 검증, provider 원래 요청 조회, stage별 동시성·backoff/Retry-After·종류별 오류 정책 |
| outbox/background_jobs의 unique·claim·lease 회수·fence finish | 실제 cleanup/reconcile/validation handler, 페이지 결과의 원자적 연결과 cleanup 완료 기록, 전체 상태 enum/복합 소유권 DB 제약 보강 |

`ResultStore`는 이번 검증의 local durable attempt envelope다. AI 이미지 bytes/R2/실제 provider 결과 회수의 성공을 증명하지 않는다. 운영 worker entrypoint는 DB recovery/outbox/stale job maintenance를 실행하며 AI/media adapter를 기본으로 설치하지 않는다. `Runner.run_once()`는 명시적으로 주입한 AI/local port만 실행하고, handler 없는 product job을 성공 처리하지 않는다. background job 결과를 ready/upload/media에 연결하는 전체 application 흐름은 후속 연동 대상이다.

## 판정·남은 항목

- **V03/V04의 이번 Task 3 범위 PASS**: 실제 PostgreSQL 실행권, 발송 경계, 프로세스 종료/새 프로세스 재시작, 보존 응답, 원자 접수, mixed resume의 26개 자동 검증이 통과했다. 전체 제품·외부 adapter 검증의 완료를 의미하지 않는다.
- 외부 AI·OAuth·R2·실제 사진·과금·배포·실기기·전체 API endpoint·전체 사진첩 완료는 실행하지 않았다. 외부 과금 exactly-once도 주장하지 않는다.
- API의 소유권/동의/expected_version/Idempotency-Key/사용량 검사는 후속 application 작업이 이 repository 앞에서 수행해야 한다.
- 전체 회귀의 Starlette/anyio BlockingPortal deprecation 경고는 이 작업 범위 밖이며 패키지 lock은 변경하지 않았다.
- 지시된 공유 checkout/편집 경계를 우선하여 별도 worktree·commit·계획 ledger·다른 에이전트를 생성하지 않았다. 승인 계획과 RED/GREEN 기록은 이 보고서에 남겼으며 총괄이 별도 코드 검토와 commit을 담당한다.

## 변경 파일

- `backend/database.py`, `backend/models.py`, `backend/alembic.ini`
- `backend/migrations/env.py`, `backend/migrations/versions/0001_workflow_foundation.py`
- `backend/generation/__init__.py`, `backend/generation/repository.py`, `backend/generation/resume_policy.py`
- `backend/worker/jobs.py`, `backend/worker/runner.py`, `backend/worker/__main__.py`
- `backend/tests/integration/conftest.py`, `backend/tests/integration/crash_worker.py`, `backend/tests/integration/test_claim_fence.py`, `backend/tests/integration/test_upload_jobs.py`, `backend/tests/integration/test_job_recovery.py`, `backend/tests/integration/test_resume.py`
- `scripts/verify-db.sh`, `scripts/verify-worker.sh`, `docs/DB-worker검증-결과.md`

README·검증계획·Makefile·manifest/lock·media·공통설정·Git index/commit/branch는 편집하지 않았다. 같은 checkout의 다른 담당자 변경은 유지했다.

## 총괄 통합 보완

새 빈 DB의 기본 Compose 기동에서 alembic_version이 없어 검증이 실패하는 것을 재현했다. local one-off migrate 서비스를 추가해 web·worker는 migration 성공 후 시작하도록 연결했다. 배포 서비스 추가·외부 자원 생성은 아니다. 검증 이미지에는 테스트가 사용하는 scripts·합성 fixture를 포함했다. DB 없는 빌드에서는 integration tests를 숨기는 collection 제외 대신 명시적 skip으로 보고하고, 실제 verify-db에서는 해당 조건을 활성화해 skip 없이 실행한다.

총괄 재검증: make verify-install 성공(67 passed, DB 26 skipped), make verify-db 26 passed, make verify-worker 14 passed, bash scripts/verify-db.sh backend/tests 93 passed·skip 0. 로그는 /tmp/mori-parent-{install,db,worker,suite}-final.log. make verify-isolation도 새 DB 두 곳의 schema 존재·HTTP·DB/media 격리·SIGTERM exit 0까지 통과했다. 최초 병렬 기동 한 번은 migrate exit 255·로그 없음으로 실패했고 합격에서 제외했다. 독립 임시 기동과 단독 격리 재실행은 성공했으며 원인은 확정하지 않았다.
