# R2 worker 및 원본 결과 복구 구현 결과

2026-10-16 Task3 `task_0298f7118457`, Dispatch `ctx_87636465ca20`.

## 변경 파일 및 경계

- `backend/storage/r2.py`: `stat`만 HEAD 기반 metadata 조회로 보완. ContentLength는 정수 0~20MiB 검사하며 원격 404에서는 stale cache 제거 후 FileNotFoundError, 원격 장애는 StorageUnavailable을 유지한다. GET 다운로드를 하지 않는다.
- `backend/storage/result_store.py`: R2ResultStore 추가. UUID attempt key, 기존 local ResultStore와 동일한 JSON payload 직렬화·envelope key/payload/sha256 규칙, 불변 원격 저장, remote load를 제공한다.
- `backend/uploads/validation.py`: factory 선택, mode snapshot 검사, thread 밖에서 실행되던 path 다운로드 수정, transient 재시도 및 삭제 sweep HEAD 확인.
- `backend/generation/fake_adapter.py`: path materialize/read를 thread로 이동하고 factory의 result_store를 사용한다. 기존 scope/fence 및 원본만 복구하는 정책을 보존한다.
- `backend/tests/integration/test_r2_pipeline.py`: 실제 PostgreSQL과 미디어 subprocess에 injected FakeS3를 결합한 23개 검증.
- 이 보고서.

settings/factory/Signer/main/worker entrypoint/dependency/lock/DTO/Git/타 worker 소유 파일은 변경하지 않았다. 기존 이 저장소의 LocalStorage, worker.runner.ResultStore 직렬화 규칙과 validation/generation 로직을 사용했다. 기존 moriai 원본 이식이나 `.env`/QA 사용자 원본 읽기는 없었다.

## 결과 원장 및 오류 정책

R2ResultStore.save/load의 synchronous remote envelope I/O는 asyncio.to_thread에서 수행하며 로컬 cache가 없어도 원격 원본으로 복구한다. 동일 payload의 중복 save만 성공하고 다른 payload는 immutable conflict를 보존한다. 잘못된 JSON, envelope shape, key, checksum, 예상 checksum, 1MiB 초과 또는 404는 load에서 None이다. StorageUnavailable은 None으로 위장하지 않고 전파한다. 원격 장애를 원본 부재로 간주하면 재호출 판단이 달라질 수 있으므로 이 정책을 coordinator에 알렸다.

ValidationWorker는 media_storage(settings)로 storage를 선택한다. snapshot의 storage_mode가 없으면 기존 local fixture와 동일하게 local로 취급하며 r2는 명시 일치가 필요하다. source materialize는 transaction 밖의 thread에서 한 번 실행한 후 MIME 검사와 normalize subprocess에 전달한다. 원격 stat/checksum/write/delete도 thread에서 실행한다. StorageUnavailable을 generic OSError보다 먼저 전파하여 run_once의 기존 retry_wait 처리로 연결한다. 404와 실제 입력 오류는 기존 영구 검증 실패 규칙을 따른다.

삭제 sweep는 각 canonical role의 원격 exists(HEAD)를 확인한다. source 404가 다른 late derived role 확인을 중단하지 않는다. canonical/scope/fence 검사와 기존 정리 key 모양을 보존하며 normalize 중 삭제, 이전 cleanup 후 late PUT, 반복 tombstone sweep을 확인했다.

FakeExecutor는 source·optimize 다운로드 및 recover_original path와 bytes 읽기를 thread에서 실행한다. execute의 원본 결과 원장은 factory.result_store(self.store)로 선택하며 Runner가 같은 원장을 주입하는 entrypoint 변경은 coordinator 소유다. 원래 attempt/output checksum과 scope를 검증하며 새 image 응답을 만들거나 execute를 재호출하지 않는다. transient는 원본 부재로 바꾸지 않는다.

## 검증

SDK 포함 기존 `mori-ai:r2-tests` image를 사용했다. 각 scripts/verify-db.sh 실행은 `.env` 없이 별도 임시 PostgreSQL 17.11 DB와 전용 volume/network를 생성하고 migration upgrade/downgrade/upgrade/check 후 테스트하고 자신이 만든 자원만 정리했다.

RED: 최초 R2 pipeline 13개 실패. 신규 ResultStore/validation factory API 부재와 기존 stat의 GET 호출을 확인했다. 첫 구현 후 12개 통과, 테스트의 async_generator/all 사용 오류 1개를 수정했다. 확대 후 아래 target 검증은 모두 통과했다.

```sh
MORI_VERIFY_TEST_IMAGE=mori-ai:r2-tests bash scripts/verify-db.sh \
  backend/tests/integration/test_r2_pipeline.py \
  backend/tests/storage/test_r2_adapter.py
```

결과: **47 passed** (R2 pipeline 23 + 기존 adapter 24), 17.88초. 원격 immutable source/blob checksum, source malformed/oversize/missing, mode 불일치, owner scope 불일치, 새 cache에서 normalize/generate, 원격 original envelope 및 blob 복구, attempt 1회 유지, 503 validation retry_wait와 recovery 장애 전파, late derived 재정리, SDK sleep 중 event loop tick과 generation SDK thread 실행을 확인했다. FakeS3 SDK 경계만 대체했으며 실제 DB·codec·미디어 subprocess를 실행했다.

기존 local 회귀 명령:

```sh
MORI_VERIFY_TEST_IMAGE=mori-ai:r2-tests bash scripts/verify-db.sh \
  backend/tests/integration/test_validation_worker.py \
  backend/tests/integration/test_generation_pipeline.py::test_portrait_landscape_inputs_preserved_and_atomic_completion \
  backend/tests/integration/test_generation_pipeline.py::test_optimize_storage_failure_resume_never_repeats_image \
  backend/tests/integration/test_generation_pipeline.py::test_forced_crash_restart_original_only \
  backend/tests/integration/test_generation_pipeline.py::test_unknown_recovery_and_delete_never_reopen_resumable_work \
  backend/tests/integration/test_generation_pipeline.py::test_generation_heartbeat_and_cancel_work
```

결과: **34 passed**, 41.84초. 기존 local validation 전체와 생성 원본 보존·복구·재시도·삭제·heartbeat 핵심 회귀가 통과했다. 전체 backend suite와 최종 install 검증은 coordinator 소유이므로 중복 실행하지 않았다.

검증 로그: `/tmp/mori-r2-worker-expanded.log`, `/tmp/mori-r2-worker-local-regression.log`. 이 결과를 확인한 뒤 해당 Task 소스를 동결했다.

## 실제 연동 및 retention 한계

실제 R2 provider network API를 호출하지 않았다. FakeS3 통과는 R2 권한·CORS·실제 브라우저 서명 왕복 성공을 뜻하지 않는다. 자동 local 원장/미디어 이관을 구현하지 않았고 R2는 새 DB/prefix 기준이다. 공개 계약·DTO 변경은 없다.

attempt envelope는 기존 local 정책과 동일하게 내부 비공개 원본 복구 기록으로 보존한다. 사용자가 사진을 삭제해도 기존 원장에 caption 원문이 남을 수 있는 retention 한계가 있다. 이 Task는 운영 개인정보 보존 정책을 확대하거나 확정하지 않으며, 실제 검증 스크립트가 만든 envelope의 명시 삭제는 coordinator 범위다.
