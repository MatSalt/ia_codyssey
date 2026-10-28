# OAuth 독립 코드 검토

2026-10-16, Orca Task `task_be6305fb7cc9`, Dispatch `ctx_c0bb68080e9c`. 구현에 참여하지 않은 fresh worker의 독립 검토다.

## 검토 상태

최종 검토 기준은 `56e9575` → `598f2d1ba169b75b95182978403c817650c7cc4e`다. 초기 frozen `8066819` 범위와 총괄의 최종 freeze 통보 이후 HTTP/service/main을 포함한 전체 OAuth 변경을 검토했다. 승인 계획, 공통계약, 네 구현 보고서 및 관련 기존 인증·화면 코드를 대조했다.

최종 frozen 범위에서 재현 가능한 Critical/Important/Minor 결함은 확인하지 못했다. 코드 리뷰 기준 진행을 막을 중요 문제가 없다. 실제 제공자 로그인 성공 및 자격증명 유효성은 미검증이며 이 판정에 포함하지 않는다.

## frozen 범위 확인

- 저장소: state/binding SHA-256만 저장하고 provider·binding·미소비·만료 조건을 단일 UPDATE RETURNING에 넣는다. 만료는 PostgreSQL clock과 비교하며 동시 소비는 한 번만 성공한다. identity별 transaction advisory lock과 User row lock, 기존 unique/FK로 중복 사용자·orphan 및 삭제 사용자 재활성화를 방지한다. 복귀 경로는 fullmatch 허용목록이다.
- provider: 고정 HTTPS endpoint, form 교환, Bearer 프로필 조회, 요청별 timeout 10초와 redirect 금지, 자동 재시도 없음. Google은 openid profile/sub, Kakao는 양의 정수 id를 신뢰하며 이메일 병합·미검증 ID token decode가 없다. JSON/토큰 크기 및 타입을 검사하고 upstream 예외 context를 제거한다.
- 설정/공개 경계: SecretStr와 repr 제외, 명시적 OAuth 변수만 Compose에 전달하고 Settings가 .env를 자동 읽지 않는다. client-config에는 알려진 provider 목록만 공개한다. R2/OpenAI 키 전달·실제 호출 추가 없음. 기존 세션 Secure 정책을 재사용한다.
- 유지관리: 만료 인덱스와 prune 삭제 조건, 실제 worker loop의 60초 스케줄 연결을 확인했다. OAuth 정리는 기존 runner/업로드 유지관리보다 앞서 같은 loop에서 실행하며 정상 경로에서 기존 유지관리가 계속된다.
- 화면: 알려진 provider·내부 복귀 경로와 오류 enum만 사용한다. 첫 /me 401에서 공개 단일키 client-config를 취소하지 않고 private query는 취소·제거한다. 만료 시 같은 소유자의 메모리 입력/요청 identity 보존과 다른 소유자 로그인/명시적 로그아웃 시 삭제가 기존 회귀 검사와 일치한다. 동의 화면을 유지한다.
- 최종 HTTP/service: router가 SPA보다 먼저 등록된다. callback 전체 query 크기/중복/값 제한, 알려진 Google metadata 및 optional issuer 검증, code/error 배타성, 모호한 cookie 거부를 확인했다. 유효 state/binding 소비를 외부 await 전에 별도 commit하고, 새 user/identity/session과 이전 세션 철회를 같은 transaction에 묶는다. 실패·취소는 세부 정보 없는 고정 내부 URL만 사용하고 성공/실패에 no-store/no-referrer와 binding 삭제를 적용한다. 세션 원문은 HttpOnly cookie에만 넣는다. Docker runtime의 `--no-access-log`와 별도 token/code 원문 logger 부재를 확인했다.

## 독립 실행 및 직접 확인 근거

1. 아래 명령을 기존 이미지, read-only 새 소스, 외부 네트워크 차단 상태로 직접 실행했다. `94 passed in 0.85s`, exit 0.

   ```sh
   docker run --rm --platform linux/amd64 --network none -v "$PWD/backend:/app/backend:ro" mori-ai:verify-tests python -m pytest -q backend/tests/test_oauth_settings.py backend/tests/test_oauth_providers.py
   ```

2. 같은 network-none 이미지에서 Python stdin/임시 fake로 `backend.worker.__main__.main()`을 실행했다. 실제 loop가 prune을 transaction context 안에서 호출하고, 이어 runner maintenance·upload scan·validation을 실행하며 종료 시 engine dispose하는 것을 검증했다. 결과: `worker cleanup scheduling/transaction/remaining maintenance/disposal: PASS`. 이 검사는 DB 삭제 자체의 통합 검증을 대신하지 않는다.
3. `/tmp/mori-oauth-repository-green.log`를 직접 확인했다. 실제 PG 대상 32개 통과와 `No new upgrade operations detected.` 기록이 있다. 테스트 소스에서 서로 다른 PG 연결의 state/identity 경합, DB clock 만료, 삭제 사용자 거부, prune 및 rollback 검사를 확인했다. 이 로그의 실행자는 저장소 worker다.
4. `/tmp/mori-oauth-frontend-build.log`를 직접 확인했다. fresh frontend build/typecheck 및 Node 43개 통과(실패 0), OAuth 실제 React 렌더 검사 6개와 기존 세션 만료·복구 검사 연결을 확인했다. 이 로그의 실행자는 총괄이다.
5. 제품 변경 범위 `git diff --check 56e9575 -- backend frontend compose.yaml Dockerfile docs/공통계약-v1.md` exit 0.
6. `/tmp/mori-oauth-http-final-green.log`를 직접 확인했다. 실제 PostgreSQL 17.11, Alembic check 및 `49 passed in 7.24s`, 임시 DB/volume/network 정리 기록이 있다. 최종 HTTP 테스트의 성공/취소/실패·세션 회전·provider 분리/동의·삭제 사용자·MockTransport·동시 callback·rollback 검사를 소스와 대조했다. 실행자는 HTTP worker다.
7. 최종 freeze 후 아래 보안 핵심 대상만 독립 재실행했다. PostgreSQL 17.11 및 upgrade → downgrade base → upgrade head → Alembic check를 거쳐 `6 passed in 3.60s`, exit 0이며 임시 DB/volume/network 정리까지 확인했다. provider는 fake이며 실제 외부 호출 없음.

   ```sh
   bash scripts/verify-db.sh \
     backend/tests/integration/test_oauth_http.py::test_state_commit_precedes_external_await_and_two_pg_connections_have_one_callback_winner \
     backend/tests/integration/test_oauth_http.py::test_rotation_transaction_rolls_back_user_session_and_revocation_on_failure \
     backend/tests/integration/test_oauth_http.py::test_known_provider_fields_are_bounded_ignored_and_issuer_checked \
     backend/tests/integration/test_oauth_repository.py::test_expired_request_rejected_even_with_stale_caller_clock \
     backend/tests/integration/test_oauth_repository.py::test_same_identity_race_creates_one_user_without_orphans
   ```

전체 suite/build의 중복 실행은 하지 않았다. 제품 소스·설정·migration·lock·Git 수정, 의존성 설치, 다른 agent 실행, .env/기존 moriai 읽기, provider HTTP·운영 데이터·유료 API 호출은 하지 않았다. 이 보고서만 편집했고 기존 코드 이식은 없다.

## 최종 합류 및 남은 검증

총괄은 `/tmp/mori-oauth-final-db.log`, `/tmp/mori-oauth-final-install.log`로 전체 DB 및 fresh build/설치 검증을 수행한다. 최종 로그 완료·exit 판정은 총괄 책임이며, 독립 리뷰는 전체 suite를 중복 실행하지 않았다. 실제 Google/Kakao 브라우저 왕복, 자격증명·콘솔 callback 등록, 제공자별 로그인/취소·계정 격리는 별도 사용자 로그인 검증 대상이다. mock/PG 성공을 실제 제공자 인증 성공으로 판정하지 않는다.

변경 파일은 이 보고서 하나이며 제품 코드나 공개 계약을 수정하지 않았다. 이번 OAuth 계약 변경은 총괄이 기존 계약/샘플에 반영한 provider 공개 목록과 승인된 OAuth 구체화이며 추가 계약 변경 권고는 없다.
