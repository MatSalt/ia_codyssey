# UI 통합·회귀 검증 — 2026-10-17

사용자가 남은 작업 1번(UI 통합·회귀 검증)을 승인했다. `jimchoi9/feat-ui-apple`의 `a6e601b4f6d1b889a7f0a67de59dc3c32a10622f`를 총괄 `feat/development-foundation`에 fast-forward로 반영했다. 기준/부모는 `e09cfe7`이며 충돌은 없었다.

## 검토

- 제품 변경은 app shell, JSX 표현·배치와 styles.css다. API·DTO·backend·업로드 훅·재시도·BGM 재생 모듈·의존성/lock은 기준과 바이트 동일하다.
- 업로드/생성/재개/저장/완성 버튼 조건과 기존 오류·복구 안내를 보존한다. 글귀 번호 이동은 history를 만들지 않는 scroll/focus 조작이며, 편집기를 모두 유지한다.
- BGM은 swipe target 밖의 viewer-frame에 배치한다. 재생과 lifecycle 구현은 이전 검증본 그대로다.
- 시안·참고 PNG는 저장소에 보존하지만 제품 bundle에서 import하지 않는다. 생성한 runtime의 frontend/dist는 HTML·JS·CSS 각1개이며 참고 PNG가 없다. BGM MP3는 runtime에 포함된다.

## 검증 범위

- 통합 대상의 깨끗한 worktree에서 정식 Docker runtime 빌드를 새로 실행했다. 타입 검사·Vite build·frontend 전체63개 검사 통과, 실패0. 통합된 소스는 이 검증 커밋과 동일하다.
- 프런트 검사에는 OAuth 옵션, upload 선택/조건부 PUT/응답 유실 재시도, 세션 초기화, 생성·재개 요청, 글귀 이탈 보호, 삭제 결과 확인, BGM7개 상태 검증이 포함된다.
- 통합 후 전용 임시 PostgreSQL에서 upload HTTP, generation pipeline, review/viewer HTTP, BGM endpoint 회귀64개가 통과했다(162.94초). 실제 AI/OAuth/R2와 사용자 QA DB는 사용하지 않는다.
- UI 담당 세션의 브라우저 검증 이력(320px/데스크톱·가짜 전체 흐름·BGM)은 `frontend/design-preview/IMPLEMENTATION.md`에 있다. 총괄의 이번 자동검증을 새 모바일 실기기 검증으로 간주하지 않는다.

## 경계와 인계

- 사용자 `.gitignore`, PDF, design/, output/을 보존했다. 원래 UI 브랜치·worktree와 독립 UI 환경을 제거하지 않았다.
- 빌드 이미지: `mori-ai:ui-integrated-runtime`. QA runtime 교체, 원격 push, Lightsail 설정·배포는 실행하지 않았다.
- 모바일 실기기·청취와 실제 외부 연동 확인은 사용자 결정대로 배포 완료 후 재개한다.
- 로그: `/tmp/mori-ui-integration-build.log`, `/tmp/mori-ui-integration-backend.log`.

최종 판정: 자동 회귀 범위 통과. API/DTO 변경 없음. 임시 검증 DB·볼륨은 정상 정리했고 사용자 QA·UI 독립 환경은 보존했다.
