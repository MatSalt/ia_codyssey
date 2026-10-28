# 승인된 UI의 제품 적용

기준 e09cfe7, 독립 Orca worktree feat-ui-apple. 사용자가 2026-10-17 전체 시안 승인 후 실제 적용을 요청함.

계획: (1) 공통 규칙·로그인/동의·책장 (2) 업로드·진행·검토·뷰어의 표현 계층 연결 (3) 독립 local DB/runtime에서 회귀 및 화면 점검 (4) 독립 리뷰 후 인계.

경계: API/DTO/의존성/백엔드/상태 전이/재시도/인증/음악 재생 구현은 변경하지 않음. 앱 shell·각 화면 JSX와 CSS만 편집. 총괄 checkout/QA/문서는 읽기 전용.

결정: 로그인·진행 장식은 자체 CSS로 구성. 시안에 합쳐진 샘플 사진은 제품에 복사하지 않음. 실제 사진은 기존 signed media 경로를 사용. 검토 화면은 모든 편집기를 유지하고 번호 링크로 이동해 기존 draft/충돌/저장 로직을 보존. 장식 시안과 차이가 있으나 새 상태 로직 없이 접근 가능하고 사진 내용을 자르지 않음.

Task 1/2: 표현 계층 적용. 주요 생성 버튼 하단 이동, 상태/오류/삭제/동의 제어 보존, BGM은 swipe target 밖에 배치하고 기존 모듈 그대로 사용.
검증 예정: Docker frontend 전체 기존 검사·타입·빌드, 독립 compose local fake AI 흐름 및 320px/desktop 점검.

## 검증 완료 — 2026-10-17

- 최종 runtime 이미지 빌드(타입 검사·Vite 포함) 성공, 기존 frontend 전체 63 passed / 0 failed. `git diff --check` 통과.
- 독립 Compose project `mori-ui-apple`, web `http://127.0.0.1:18174`, 전용 PostgreSQL/media volume. local storage, 개발 로그인, 가짜 AI만 사용. 실제 OAuth/R2/OpenAI 자격증명 복사·호출 없음. 총괄 QA/DB/checkout 변경 없음.
- Orca profile `Mori UI isolated`에서 개발 로그인→명시적 동의→빈 책장→새 사진첩→저장소 fixture 2개 업로드→검증 완료→순서 이동→가짜 생성→글귀 편집/저장→완성→감상 흐름 확인.
- 320px 업로드·검토·감상·책장 가로 넘침 없음. 업로드 이미지 실패 이벤트와 offline 재현에서 복구 버튼 bottom393px < 이미지 영역 bottom409px, 잘림 없음. reconnect 후 사진 복원 확인.
- 미저장 상태에서 완성 비활성화. 번호 이동 후 입력 보존, history length3 유지, 이동 대상에 키보드 포커스 전달. 저장 후 서버 응답 ‘저장 완료’, 완성 및 뷰어에 수정 글귀 반영.
- BGM: 최초 paused=true, preload=none, volume=.35, loop=true. 실제 버튼 클릭 후 paused=false, 1/2 페이지 유지. 뷰어 이탈 후 같은 audio 객체 paused=true. 재생 모듈 7개 회귀 검사 통과. Orca 탭 전환은 document.hidden을 변경하지 않아 실제 백그라운드 전환 실기기 검증으로 간주하지 않음.
- 1064px 책장 4열(각212px), scrollWidth=innerWidth=1064. 기본 창 로그인/빈 책장/책장/감상 캡처 확인. 모바일 emulation 캡처에 타일링 결함이 있어 작은 화면은 DOM 치수로 검증했으며 실기기 검증은 아님.
- 독립 읽기 전용 리뷰: API/인증/상태 로직 회귀 없음. 복구 버튼 공간 보완, hash 링크를 이력 없는 스크롤·포커스 버튼으로 교체. 빈 책장의 CTA가 설명을 가리지 않게 일반 흐름 배치.
- BackgroundMusic.tsx, musicPlayback.ts, api/types.ts, package.json, package-lock.json은 기준 e09cfe7과 바이트 동일. 다른 변경도 JSX 표현/배치와 styles.css에 한정.

Task 3/4: 완료. 외부 배포·총괄 브랜치 병합은 수행하지 않고 UI worktree를 보존한다. 실제 OAuth/R2/OpenAI end-to-end 및 모바일 청취·실기기 접근성 검증은 이번 검증에 포함하지 않음.

출처: 사용자 승인 design/references/apple-ui-concepts 시안과 이 worktree의 디자인 미리보기. 제품에 참고 PNG/Apple 토큰 덤프 import 없음. 기존 moriai 코드 이식 없음.

## 사용자 마무리 결정

현재 UI 단계는 여기서 마무리하며 모바일 실기기 검증은 배포 작업이 끝난 뒤 재개한다. 사용자는 UI 변경 커밋 및 총괄 세션 전달을 승인했다. 이번 세션은 병합·푸시·배포를 수행하지 않는다.


## 2026-10-18 UI components 후속 작업

별도 `jimchoi9/ui-components` 워크트리에서 공통 부품과 실제6화면 표현을 재구성했다. 기존 보고서의 검증과 혼동하지 않도록 최신 근거·미완료·실행 자원은 [UI-COMPONENTS-PROGRESS.md](UI-COMPONENTS-PROGRESS.md)에 기록한다. 제품 대표 사진·실기기·최종 시각 검토는 남아 있다.
