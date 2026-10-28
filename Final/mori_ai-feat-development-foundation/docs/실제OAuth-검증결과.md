# Google·Kakao OAuth 구현·검증 결과

2026-10-16. 승인 계획: [실제 OAuth](superpowers/plans/2026-10-16-real-oauth.md).
현재 판정: **코드·자동 검증·독립 검토 완료, 사용자 Google·Kakao 실제 로그인 성공 및 서버 기록 확인**.

## 구현 범위

- 기존 AuthIdentity를 재사용하여 제공자 계정과 사용자를 연결한다. 이메일은 수집·자동 병합하지 않는다.
- TTL600초의 일회용 로그인 요청을 DB 해시와 브라우저 바인딩 cookie로 검증한다. state 소비는 외부 token 교환 전에 commit하며 중복 callback의 provider 교환·세션 발급은 한 번만 허용한다.
- Google/Kakao 고정 HTTPS REST endpoint, timeout10초, redirect/자동 retry 금지, 응답 최대1MiB·token 최대16KiB, 일반 오류만 사용한다. 미검증 ID token decode로 인증하지 않는다.
- 기존 동의·세션·CSRF·소유권을 유지하며 성공 callback에서 이전 세션 철회와 새 세션을 같은 transaction으로 저장한다.
- 공개 client-config에 auth_providers만 추가한다. UI에는 활성 제공자 링크와 일반 실패/취소 안내가 표시된다. 공개 단일키 설정은 401 이후에도 보존하고 사용자별 데이터는 삭제한다.
- 만료 로그인 요청을 worker에서 60초 주기로 정리한다. Uvicorn 기본 access log를 꺼 callback query의 code가 기록되지 않도록 한다.
- OAuth 설정만 Compose에 전달한다. R2/OpenAI 키·실제 AI 호출·배포는 연결하지 않았다. 이번 작업의 AI 검증 비용은 USD0이다.
- 기존 moriai의 코드·설정·데이터는 읽거나 이식하지 않았다.

## 실행 근거

| 범위 | 결과 | 근거 |
|---|---|---|
| root 설정·공개 config | RED 후 14 passed | /tmp/mori-oauth-config-green.log |
| identity/state 실제 PostgreSQL | 32 passed, migration 왕복·Alembic check | [저장소 결과](OAuth-저장소-구현결과.md) |
| provider MockTransport | 80 passed, 외부 요청 없음 | [adapter 결과](OAuth-provider-구현결과.md) |
| callback/session 실제 PostgreSQL | 49 passed | [HTTP 결과](OAuth-HTTP-구현결과.md) |
| fresh frontend stage | 타입·Vite·Node43 통과 | /tmp/mori-oauth-frontend-build.log |
| make verify-install | exit0, 201 passed/DB281 skipped, Node43·pip check 통과 | /tmp/mori-oauth-final-install.log |
| 독립 전체 코드 검토 | Critical/Important/Minor 확정 결함0, 독립 unit94 및 DB핵심6 통과 | [독립 검토](OAuth-독립검토.md) |
| 첫 실제 DB 전체 | 481 passed/1 failed, 254.84초 | /tmp/mori-oauth-final-db.log |
| 종료 테스트 fixture 수정 | SIGTERM 대상1 passed, 제품 변경 없음 | [경합 수정](OAuth-전체회귀-경합수정.md) |

첫 전체 실패는 자식 PID 파일의 exists 관찰 직후 빈 내용을 읽은 ValueError였다. 테스트 자식이 같은 디렉터리 임시파일에 PID를 완전히 쓴 뒤 replace하도록 변경했다. timeout 증가·skip·제품 동작 변경으로 실패를 감추지 않았으며 부모 종료0/자식 소멸 검사는 유지한다. 최종 전체 회귀 로그는 /tmp/mori-oauth-final-db-green.log이며 완료 후 아래 판정에 기록한다. fixture 반영 image 재빌드 로그는 /tmp/mori-oauth-fixture-image.log다.

## 실제 브라우저와 사용자 입력 대기

전용 Compose project mori-oauth-qa를 http://127.0.0.1:8000 에 기동했다. 전용 DB·media volume·새 로컬 DB 비밀번호를 사용하며 운영 자원은 연결하지 않았다. local HTTP 세션 cookie만 명시적으로 허용하고 개발 가짜 로그인·AI는 모두 비활성화했다.

Orca 페이지 88cce19f-4b35-4d8b-9f8a-1e72bd998692의 실제 DOM에 Google/Kakao 로그인 링크가 나타나고 /me401로 로그인 대기임을 확인했다. 사용자에게 Google 계정 선택·비밀번호/MFA를 직접 진행해 달라고 요청했다. 실제 Google/Kakao callback 성공·콘솔 등록·취소·계정 격리는 아직 확인하지 않았으며 mock 성공으로 대체하지 않는다. 사용자 입력이 필요한 동안 QA 서버와 해당 탭은 유지한다.

.env는 값 노출 없이 필수 항목/콜백 origin/모델/예산을 확인했고 권한600과 Git/Docker 제외를 확인했다. QA 설정은 /tmp/mori-oauth-qa-state.json 권한600에 OAuth 값과 QA 전용 설정만 보관했다. 값은 이 문서나 Git에 기록하지 않는다. 실제 검증 종료 후 전용 QA·비밀 임시파일만 정리한다.

## Orca 추적과 한계

Run run_e4206c698a2c에서 repository task_37f81e5ac8a7, provider task_11f92bb7ef9f, frontend task_87d53f411fad, HTTP task_fb54096d1e62, 독립 검토 task_be6305fb7cc9, fixture 수정 task_4e34d86ed258를 실행했다. 각 성공 Dispatch는 완료 보고 이후 재사용하거나 worker-release하고 Delivery를 처리했다.

provider 첫 시동 ctx_8a484c59665d는 Codex CLI 업데이트 메뉴에 prompt가 걸려 agent_prompt_stalled로 실패했다. 당시 터미널에 npm 전역 Codex 업데이트 성공과 재시작 안내가 출력됐다. 실패 Dispatch의 터미널을 release하고 새 Dispatch ctx_1b3e29051b8f로 성공했으며 이를 정상 최초 실행으로 위장하지 않는다. 제품 의존성/lock/host Node runtime은 변경하지 않았다.

배포·R2·실제 AI·권리 확보 BGM·HDR·모바일 실기기는 후속 범위다. 사용자 원본 PDF·output 및 .gitignore 변경은 보존했다.

## 최종 자동 검증 판정

fixture 수정 후 실제 PostgreSQL 전체 단일 실행은 **482 passed, fail/skip0, 196.69초, exit0**이다. /tmp/mori-oauth-final-db-green.log에서 migration 왕복/Alembic check와 전용 테스트 DB·network·volume 정리를 확인했다. 기존 AnyIO deprecation warning1개는 유지된다. Node43·tsc/Vite 및 재현 설치도 통과했다. fixture 반영 cached 이미지 재빌드는 exit0이며 제품 의존성·설정·frontend 소스는 앞선 재현 빌드와 같다. 최종 runtime sha256:30169653a37cd1724fe8c7bc64fe37285839f19b0bc350b6a5a93b81ff50db88, verification sha256:fecfb1137bce6c6a595e4bd45f5ec6e63a9618942f95de60124be74fb8986a41(Linux amd64).

실제 QA worker에 만료된 합성 로그인 요청1개를 넣고 60초 정리 주기 뒤 해당 행0개를 확인했다. worker 로그의 ERROR/Traceback도0이다. 실제 사용자 OAuth identity는 현재0개이며 Google/Kakao 실제 로그인 성공은 계속 미검증이다. QA 서버는 제품 코드가 동일하고 PID 테스트 fixture 수정 전인 runtime sha256:3200254cdab45552ce0187d2f3e8d9785b4426132e1430674ff77e1cd2ffe69b로 동작한다. 사용자 로그인 요청을 끊지 않도록 테스트 fixture만 달라진 이유로 재시작하지 않았다.

판정: OAuth 코드 구현·자동 검증·독립 검토 완료. 실제 앱 자격증명·콘솔 등록·계정 왕복 검증은 사용자 로그인 후 계속한다. QA 환경은 이 후속 검증을 위해 유지하며 이를 배포 또는 외부 인증 성공으로 계산하지 않는다.

## 사용자 실계정 로그인 확인 (최신)

사용자가 “구글 카카오 모두 로그인 성공했어”라고 확인했다. 같은 전용 QA DB를 read-only로 확인하여 Google identity 사용자1명·동의 기록1개, Kakao identity 사용자1명·동의 기록1개, 서로 다른 사용자 총2명을 확인했다. 확인 시 Google 활성 세션0개, Kakao 활성 세션1개이며 삭제된 사용자0명이다. 만료 정리 전 소비 완료 로그인 요청2개도 관찰했다. 계정 식별자·표시 이름·cookie·code·token·secret 값은 출력하거나 문서에 저장하지 않았다.

실제 Google/Kakao 앱의 정상 인증·callback·사용자 생성·동의 저장 경로가 작동한 근거다. 최초 Orca 검증 탭은 /me 및 /albums401이어서 현재 로그인 화면을 총괄이 직접 재확인한 것으로 계산하지 않는다. 사용자가 성공을 확인한 브라우저의 UI와 서버의 provider별 기록을 함께 근거로 삼는다. 직접 본인이 입력한 비밀번호/MFA는 수집하지 않았다.

실제 제공자 취소·재로그인 전체 조합·다른 계정 자원 교차 접근 검사는 별도 실제 시나리오로 남는다. 해당 실패/격리 동작의 자동 DB 검사는 통과했다. 사용자 성공 확인을 모든 실제 시나리오 완료로 확대하지 않는다. 다음 준비 대상은 R2 실제 저장소 연동이며 AI 호출·비용은 여전히0이다. 후속 로컬 연동에서 사용할 수 있도록 QA 서버는 유지하고, 해당 QA 종료 시 전용 자원과 private 설정 파일만 정리한다.
