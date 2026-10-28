# OAuth 서비스·HTTP Task2 구현 결과

2026-10-16 승인 계획의 Task2 서비스·HTTP 배정 범위를 완료했다. 외부 제공자 실호출 없이 전용 PostgreSQL 및 fake adapter/MockTransport로 검증했다.

## 변경 파일과 인터페이스

- `backend/auth/oauth_service.py`: `start_login(factory, settings, provider, return_to) -> (url,state,binding)` 및 `complete_login(factory, settings, provider, code, state, binding, previous_session_token, *, client=None) -> (raw_session,return_to)`. optional client는 호출자가 소유하고 서비스가 닫지 않는다. `OAuthLoginError`, 그 하위 `OAuthLoginCancelled`, 취소/실패 처리용 `reject_login`을 추가했다.
- `backend/auth/oauth_routes.py`: full path `/api/v1/auth/{provider}/start|callback`의 `router`. 총괄이 main router 등록을 완료했다. binding cookie 이름은 `mori_oauth_binding`이다.
- `backend/tests/integration/test_oauth_http.py`: 실제 DB 대상 49개 검사. 별도 fixture에서 독립 로그인 요청 테이블을 테스트 전후 정리한다.
- 이 보고서.

Task1 types/repository/model, provider adapter, Settings, main, Compose, migration, worker, Git은 편집하지 않았다. 기존 서비스 원본 이식·의존성 설치·agent spawn 없음. `.env`와 기존 moriai 읽기 없음. 초기 지시의 읽기 경계를 총괄에게 확인했고 main/settings 등 일반 소스는 읽기 허용, 편집 금지로 명확화됐다.

## 구현 동작

시작은 설정된 Google/Kakao만 공개하며 미설정/미지원 404, 잘못된 복귀 경로와 start query 오염은 422다. `token_urlsafe(32)`로 서로 다른 state/binding을 생성하고 SHA-256 해시만 repository에 넘긴다. TTL은 600초이며 복귀 허용목록은 Task1 저장소 검증을 그대로 사용한다. binding cookie는 HttpOnly/Lax/Path=/이며 Secure 여부는 기존 환경 설정을 따른다.

callback은 state/code/error 등 길이·중복·제어문자·알 수 없는 query를 검증하고 code/error 동시 입력을 거부한다. state와 binding은 base64url 43~128자로 제한한다. binding 또는 이전 세션 cookie 이름이 중복되면 모호한 값을 사용하지 않는다. 기존 세션 cookie는 성공한 같은 브라우저 callback에서만 회전 대상으로 검증한다.

총괄의 질문 응답에 따라 Google `scope/authuser/prompt/hd` 및 양쪽 `error_description/error_uri`는 제한 길이·단일값을 확인하고 인증 판단 없이 무시한다. optional `iss`는 Google `https://accounts.google.com`, Kakao `https://kauth.kakao.com`에 정확히 일치해야 한다. 설명·URI를 응답·redirect·로그로 복사하지 않는다.

로그인 요청 소비는 독립 트랜잭션에서 commit한 뒤 외부 token 교환을 await한다. 교환 실패·timeout·삭제 identity·provider 불일치 시 세션을 만들지 않고 generic 실패로 처리한다. 새 identity/user 및 새 session 생성과 유효한 이전 세션 철회는 하나의 트랜잭션이다. 만료·철회·삭제 사용자 이전 세션은 안전하게 무시한다. 잘못된 callback이나 다른 브라우저 실패는 기존 세션을 철회하지 않는다.

`access_denied` 취소는 유효한 state/binding을 먼저 소비한 경우에만 `/login?auth_error=cancelled`로 이동한다. 나머지 실패는 `/login?auth_error=failed`다. callback 성공·실패 응답은 no-store/no-referrer이며 binding cookie를 삭제한다. 성공 세션 원문은 HttpOnly cookie에만 전달하고 URL에 넣지 않는다. 코드/state/binding/토큰/제공자 오류 상세를 로그로 쓰는 코드는 추가하지 않았다.

## 실행 검증

모든 DB 실행 명령: `bash scripts/verify-db.sh backend/tests/integration/test_oauth_http.py`

- 초기 RED: service 부재로 `2 passed, 35 errors`. `/tmp/mori-oauth-http-initial-red.log`.
- 동작 RED: 빈 route router 및 NotImplemented service로 `43 failed, 2 passed`. route 부재 404 및 미구현 service로 실패했다. `/tmp/mori-oauth-http-behavior-red.log`.
- 첫 GREEN: `45 passed in 6.90s`, exit 0. `/tmp/mori-oauth-http-green.log`.
- 최종 GREEN: `49 passed in 7.24s`, exit 0. `/tmp/mori-oauth-http-final-green.log`.
- PostgreSQL `17.11`; 각 script에서 upgrade → downgrade base → upgrade head → Alembic check 성공.
- 허용 네 경로 대상 `git diff --check`: exit 0.

검증은 기존 Docker image의 read-only backend mount를 사용해 새 소스를 실행했다. `/dev/null` Compose env 및 전용 임시 DB guard를 유지했고 임시 DB/volume은 script가 정리했다. Docker/Orca socket은 elevated 도구로 접근했다. provider 실모듈 import 및 Google/Kakao 실제 adapter의 MockTransport 연결도 최종 GREEN에 포함된다.

49개 검사는 시작 TTL/해시/무작위성, Secure 및 명시적 로컬 insecure cookie, 복귀 경로 우회, provider 미설정, 중복/unknown/oversized query, 알려진 metadata/issuer, state·binding·provider 불일치와 만료·재사용, 취소 검증, provider timeout·오류·identity 불일치, 새 세션/이전 세션 회전 및 실패 보존, 삭제 identity, 제공자별 사용자·동의 격리, 만료 이전 세션, 다른 브라우저 실패, MockTransport 연결, 회전 트랜잭션 실패 rollback을 확인한다.

동시 callback 검사는 두 consume 트랜잭션을 서로 다른 실제 `pg_backend_pid()` 연결에 고정하고 barrier로 시작한다. 성공 1개·provider 교환 1개·세션 1개로 수렴했다. provider 교환 fake 내부에서 별도 DB 연결로 이미 commit된 consumed_at을 관찰해 외부 await 전에 소비 commit을 확인했다.

## 남은 범위와 계약

공개 공통계약 파일 변경은 없다. 계획의 exact 서비스 인터페이스를 보존하고 허용된 optional client 및 내부 typed error를 추가했다. root가 소유한 worker 만료 정리 연결과 access log/bootstrap 설정은 이 작업자가 검증 완료로 주장하지 않는다.

전체 backend suite, make verify-install, 독립 전체 리뷰, frontend/실제 브라우저 Google·Kakao 왕복 및 실계정 격리·취소는 총괄과 Task3 범위다. 이번 성공은 실제 PostgreSQL과 모의 제공자 교환 검증이며 실제 OAuth 서비스 인증 성공이 아니다. Git commit/배포는 수행하지 않았다.
