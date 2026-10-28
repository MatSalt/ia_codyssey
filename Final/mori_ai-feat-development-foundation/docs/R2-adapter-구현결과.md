# R2 low-level adapter 구현 결과

2026-10-16, Task1 (`task_b20e2d616708`, Dispatch `ctx_4b0c1dffce08`).

## 변경 범위

- `backend/storage/r2.py`: `R2Storage(settings, *, client=None)`, `StorageUnavailable` 추가.
- `backend/tests/storage/test_r2_adapter.py`: 원격 경계 fake client 기반 24개 검증.
- 이 보고서 외 설정, factory, signing 통합, DTO, dependency/lock, worker entry, Git 변경 없음.
- 기존 `backend/storage/local.py`의 canonical key 정규식·20MiB 한도·안전한 cache 경로 검사 재사용. 기존 moriai 및 `.env` 접근 없음. 외부 원본 코드 이식 없음.

## 구현 동작

원격 GetObject를 `path/stat/checksum`의 기준으로 삼는다. 읽기는 20MiB 한도로 제한하고 ContentLength와 실제 stream 길이도 검사한다. stream을 항상 닫으며 임시 파일과 atomic replace로 cache를 materialize한다. 원격 404에서는 stale cache를 제거한다. HeadObject 기반 exists와 remote DeleteObject 기반 멱등 삭제를 제공한다.

canonical key는 기존 UUID/UUID/UUID/role namespace만 받는다. derived write는 WebP MIME과 `IfNoneMatch='*'`를 사용한다. 412/409 충돌은 원격 bytes SHA256이 같은 경우만 성공하며 local cache로 성공을 판단하지 않는다. attempt envelope는 별도 UUID 검사와 `attempts/<UUID>.json` namespace, 1MiB 한도, 불변 JSON MIME 저장 메서드를 사용한다. envelope JSON 구조의 생성·검증은 이 adapter 밖의 책임이다.

sign_put/get/head는 고정 client endpoint에서 SDK presigning만 사용한다. PUT은 MIME·ContentLength·IfNoneMatch를 서명하고 만료 1~900초, GET/HEAD는 1~300초를 허용한다. ContentLength를 frontend required_headers에 넣는 변경은 하지 않았다. SDK는 lazy import하며 explicit credentials, sigv4, path addressing, total_max_attempts=1, connect/read timeout=10/30, checksum when_required로 생성한다.

원격 서비스/네트워크 오류는 원문 없는 StorageUnavailable, NoSuchKey/404는 FileNotFoundError, SDK parameter 검증 오류는 원문 없는 ValueError로 변환한다. 변환 예외는 handler 밖에서 발생시켜 원래 예외의 cause/context를 보존하지 않는다. 원문 로그를 생성하지 않는다.

## 검증 근거

명령:

```sh
docker run --rm --platform linux/amd64 \
  -v /Users/choijimin/dev/active/mori_ai/backend:/app/backend:ro \
  mori-ai:verify-tests python -m pytest -q backend/tests/storage/test_r2_adapter.py

docker run --rm --platform linux/amd64 \
  -v /Users/choijimin/dev/active/mori_ai/backend:/app/backend:ro \
  mori-ai:verify-tests python -m pytest -q
```

- 최초 RED: adapter 파일이 없는 상태에서 16개 테스트가 ModuleNotFoundError로 실패했다. 이는 아직 API가 없는 상태의 collection/setup 실패이며 assertion 실패와 구별한다.
- 최초 구현 GREEN: 16 passed.
- stream 실제 한도·truncated stream·읽기 중 실패·409 conflict·parameter 오류·symlink·envelope read bounds 보강: 23 passed.
- SDK 구성 검증 추가 후 최종 전체 결과: 225 passed, 281 skipped, 1 warning (Starlette/AnyIO 기존 DeprecationWarning).
- DB 환경 미주입으로 DB 의존 281개는 skip이며 실제 DB 통합 성공으로 주장하지 않는다.
- 동시 writer 2개의 서로 다른 payload에서 정확히 하나만 성공하고 원격 객체가 덮어써지지 않음을 확인했다.

## 남은 통합 및 실제 검증

현재 테스트는 기존 Docker test image와 client injection을 사용한다. 실제 boto3 model의 IfNoneMatch 지원, 실제 presigned URL signed headers와 브라우저 PUT/HEAD/GET, R2 연결·권한·CORS·삭제는 총괄의 새 dependency image 및 실제 검증 범위다. 테스트의 SDK 구성 검사는 모듈 double이므로 실제 SDK 기능 검증을 뜻하지 않는다. 이 작업은 실제 R2 API를 호출하지 않았다. 공개 계약·DTO 변경은 없으며 설정/factory/worker 연결은 총괄과 해당 worker 소유다.
