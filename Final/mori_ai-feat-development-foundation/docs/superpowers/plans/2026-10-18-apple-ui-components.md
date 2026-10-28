# 시안 기반 UI 컴포넌트 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after user review. 현재는 계획 검토 단계이며 코드 구현·워크트리 생성·커밋·배포를 시작하지 않는다.

**Goal:** 사용자 시안 6장의 구성·여백·타이포그래피·사진 크기·유리 효과를 실제 제품 화면에 재현하고, 같은 컴포넌트를 사용하는 미리보기로 검증한다.

**Architecture:** 기존 화면과 훅이 인증·API·업로드·저장·복구 상태를 소유한다. 공통 UI는 props와 callback만 사용하는 표현 컴포넌트로 추출한다. 화면별 조합 컴포넌트는 해당 feature에 두고, 미리보기에서도 제품용 컴포넌트를 직접 사용한다.

**Tech Stack:** 기존 React 19 / TypeScript / React Router / TanStack Query / CSS / Vite. 신규 UI 라이브러리·폰트 패키지·Storybook 의존성 없음.

**Spec:** 이번 대화에서 합의한 공통 컴포넌트 분리, 로그인 우선 비교, 실제 사진 비율 보존. 시각적 원본은 `design/references/apple-ui-concepts/01-login.png`부터 `06-viewer-bgm.png`까지 6장이다. 제품 상태·정렬·동의는 `docs/공통계약-v1.md` v1.6을 따른다. 과거 preview는 참고이며 새 시안 충실도의 판정 기준이 아니다.

## 검토할 핵심 결정

1. **로그인 우선 확인:** 공통 부품과 로그인 화면을 먼저 만들어 실제 캡처로 검토받고, 확인 후 나머지 5개 화면을 적용한다.
2. **사진 표시:** 표지·작은 썸네일은 기존처럼 cover를 허용한다. 검토·감상 본문은 contain으로 사진 전체를 보존하고 여백은 따뜻한 흰색으로 처리한다. 따라서 세로로 길게 채운 시안과 실제 3:4 사진 사이에는 의도적인 차이가 있다.
3. **대표 사진:** 현재 별도 로그인 사진 파일은 없다. 1차 미리보기는 시안의 사진 영역만 CSS viewport로 보여주는 검토 전용 소재를 쓴다. 제품용 대표 사진은 사용자 제공 파일을 우선하며, 없으면 별도 이미지 제작 승인을 받아 준비한다. 시안 전체 PNG를 제품의 사진 소재로 배포하거나 검토용 대체 소재를 최종 완료로 처리하지 않는다.
4. **순서 변경:** 이번에는 기존 앞으로/뒤로 이동을 작은 조작 메뉴로 정리한다. 시안의 날짜순은 현재 정렬 상태 표시이며 드롭다운으로 위장하지 않는다. 길게 눌러 드래그하는 기능·날짜순 복귀는 별도 동작 변경이므로 이번에 추가하지 않는다.
5. **동의:** 시안의 ‘계속하면 동의’ 문구를 복사하지 않고, 로그인 후 기존 명시적 동의 절차를 같은 디자인으로 유지한다.

## Global Constraints

- 기반 커밋은 `b01d22e`. Orca로 해당 커밋 기반 UI 전용 워크트리를 만들고 시작 시 기반을 검증한다. 다른 세션의 배포 자동화 변경은 포함하지 않는다.
- 시안은 현재 미추적 파일이다. 실행 승인 후 6장만 별도 워크트리에 복사하고 해시를 비교한다. PDF/output/환경 파일/사용자 데이터는 복사하지 않는다. 커밋 대상 여부는 최종 인계에 명시한다.
- 테스트 서버·Compose project·DB·media volume을 별도로 사용한다. 포트는 18180/18181을 후보로 점유 확인 후 선택하고 기록한다. 운영·기존 QA 서버를 교체하지 않는다.
- backend, API/DTO, dependency/lock, 배포 파일, 전처리 훅 `useUploads.ts`/`preprocess.ts`, 재생 로직 `musicPlayback.ts`는 수정하지 않는다. 기존 auth/album/review 화면의 데이터 처리 코드는 유지한다.
- 시스템 폰트 사용. Apple 전용 폰트 파일·네이티브 유리 효과와 동일하다고 주장하지 않는다. 새 외부 이미지·폰트 요청을 제품에 추가하지 않는다.
- 시계·배터리·홈 바는 웹에서 그리지 않는다. safe-area와 동적 viewport를 사용한다. 버튼 최소 터치 영역 44px, 본문 포커스·키보드·대비·reduced-motion·blur 미지원 대체 스타일을 유지한다.
- 미리보기 전용 코드/샘플/시안 PNG는 제품 엔트리에서 import하지 않는다. 제품 컴포넌트는 preview에 의존하지 않는다.
- 계획 승인 → 공통/로그인 검토 → 나머지 화면/회귀 검증 순서. 승인 없는 커밋·푸시·병합·배포 없음.

## 시각 기준과 범위

원본은 약 852×1846px의 모바일 시안이다. 426 CSS px 폭에서 비교하되 OS 상태 영역은 비교 대상에서 제외한다. 아래 수치는 초기 구현 기준이며 로그인 검토에서 확정하고 다른 화면에 일괄 적용한다.

| 항목 | 초기 기준 |
|---|---|
| 배경/본문/보조 | #FAF9F6 / #171719 / #68686D |
| 모바일 좌우 여백 | 20px; 360px 미만에서는 16px |
| 제목 / 본문 / 보조 | 32px·1.25·700 / 17px·1.5 / 13px·1.4 |
| 사진 모서리 / 유리 패널 | 18px / 24px |
| 주 버튼 | 높이 56px, 완전한 캡슐, 17px·600 |
| 유리 재질 | 반투명 흰색, 흰색 1px 테두리, blur 20px, 약한 외부 그림자·내부 하이라이트 |
| 사진 그리드 | 모바일 2열·간격 12px, 넓은 책장 3~4열 |
| 검토/감상 | 본문 사진 3:4 전체 표시; 모바일 한 장 중심, PC 최대 폭 제한 |

비교 항목은 제목/사진/CTA의 위치·크기, 줄바꿈, 여백, 모서리, 색·그림자 순이다. 합성 이미지 차이·글꼴 렌더링 차이까지 합친 픽셀 점수 하나로 합격을 판단하지 않는다. 320/390/426/430/1064px에서 가로 넘침과 버튼 가림이 없어야 한다.

## 파일과 컴포넌트 경계

| 경로 | 책임 / 인터페이스 |
|---|---|
| `frontend/src/styles/tokens.css` | 위 디자인 토큰·spacing·레이어·safe-area 변수 |
| `frontend/src/components/ui/GlassButton.tsx` | native ButtonHTMLAttributes + `variant:'primary'\|'secondary'\|'danger'`, 기본 type=button. 링크는 버튼 중첩 없이 공통 CSS class 적용 |
| `frontend/src/components/ui/IconButton.tsx` | native button props + 필수 `label:string`, `children:ReactNode`; aria-label 제공 |
| `frontend/src/components/ui/GlassPanel.tsx` | div HTMLAttributes와 children; 데이터 요청 없음 |
| `frontend/src/components/layout/ScreenHeader.tsx` | `title:string`, `subtitle?:string`, `leading?:ReactNode`, `trailing?:ReactNode`; 화면 제목·뒤로가기·계정 메뉴 슬롯 |
| `frontend/src/components/layout/BottomActionBar.tsx` | `children:ReactNode`; sticky 하단·안전 영역, 콘텐츠 가림 방지 |
| `frontend/src/components/media/PhotoFrame.tsx` | `children:ReactNode`, `ratio:'portrait'\|'square'`, `fit:'contain'\|'cover'`; 이미지 표시만 담당 |
| `frontend/src/components/media/PhotoThumbnail.tsx` | `label:string`, `selected:boolean`, `onSelect:()=>void`, `children:ReactNode`; 선택 버튼과 테두리 |
| `frontend/src/features/auth/LoginView.tsx` | `hero:ReactNode`, `actions:ReactNode`, `feedback?:ReactNode`; 로그인 구성. OAuth·동의·dev 인증은 AuthGate 소유 |
| `frontend/src/features/albums/AlbumCard.tsx` | `title`, `meta`, `cover`, `status`, `destination`, `menu`; 생성/삭제 요청 없음 |
| `frontend/src/features/uploads/UploadPhotoCard.tsx` | `position:number`, `photo:ReactNode`, `status:ReactNode`, `actions:ReactNode`; 화면 상태 조합 |
| `frontend/src/features/generation/PhotoStack.tsx` | `photos:ReactNode[]` 최대 3장; 부족하면 중립 플레이스홀더 |
| `frontend/src/features/generation/GenerationSteps.tsx` | `steps:{label:string,status:'pending'\|'running'\|'complete'\|'attention'}[]`; 서버에서 도출한 상태 표시 |
| `frontend/src/features/review/CaptionEditor.tsx` | `value`, `count`, `disabled`, `invalid`, `onChange`, `actions`, `feedback`; 서버 저장/초안 원장 없음 |
| `frontend/src/features/review/ThumbnailStrip.tsx` | `items:{id:string,label:string,content:ReactNode,dirty:boolean}[]`, `activeId`, `onSelect`; ID 기반 전환 |
| `frontend/src/features/viewer/ViewerNavigation.tsx` | `index:number`, `total:number`, `onPrevious`, `onNext`; 경계 비활성 버튼 |
| `frontend/src/design/ComponentsPreview.tsx` | 제품 컴포넌트를 직접 import한 상태별 미리보기; API 호출 없음 |
| `frontend/design-preview/components.html` | 위 미리보기 독립 진입점 |

`AlbumGrid`/`PhotoSelectionGrid`는 초기에는 각 feature CSS grid로 충분하다. 재사용되지 않는 단순 wrapper를 추가하지 않는다. 기존 `SignedPhoto`의 URL 실패·갱신은 유지하고 PhotoFrame 안에 배치한다. 기존 `BackgroundMusic`은 재생 수명주기를 그대로 유지하며 버튼 표현만 공통 스타일에 맞춘다.

## Review Focus

- 비활성/로딩/긴 한글/긴 앨범 제목/50장 목록: 버튼 동작과 레이아웃 유지 (Task 1, 3).
- 페이지 A 미저장·저장 중에 B로 전환: A의 입력·저장 결과 보존, 다른 페이지 수정 여부도 완성 차단에 반영 (Task 4).
- 전처리·전송 실패·같은 요청 재시도·로그아웃: 미디어 v1.6 동작과 비공개 데이터 초기화 유지 (Task 3, 5).
- 만료된 사진 URL·unknown 생성 상태·409 저장 충돌: 원래 오류/복구 액션에 접근 가능 (Task 3, 4).
- BGM 조작과 사진 넘김 충돌·모바일 키보드·브라우저 뒤로가기: 원치 않는 넘김/데이터 유실/버튼 가림 없음 (Task 4, 5).

## Tasks

### Task 1. 공통 부품과 비교 미리보기

**Files:** 위 `components/**`, `styles/tokens.css`, `styles.css`, `design/ComponentsPreview.tsx`, `design-preview/components.html`; 검사 `frontend/tests/ui_components.test.mjs`.
**Consumes:** 현재 native button/link 동작과 접근성 규칙. **Produces:** 표의 공통 컴포넌트 props와 CSS 토큰.

- [ ] 기존 frontend 빌드/74개 검사 결과를 기준으로 남긴다. 실패하면 UI 변경 전에 원인을 구분한다.
- [ ] 공통 버튼 기본 type=button, disabled일 때 클릭 차단, 아이콘 버튼 이름, 썸네일 선택 상태를 검증하는 최소 React 렌더링/브라우저 검사를 추가한다. 단순 class 문자열을 복제하는 검사는 작성하지 않는다.
- [ ] 토큰·기본 컴포넌트를 구현하고 normal/focus/disabled/pending/긴 문구 상태를 같은 preview에 구성한다.
- [ ] 원본 옆 보기와 투명도 조절 overlay를 preview에 추가한다. 제품 컴포넌트와 별도 복제품을 만들지 않는다.
- [ ] 320~1064px, 키보드 조작, blur 미지원/reduced-motion을 확인하고 비교 캡처를 남긴다.

### Task 2. 로그인과 화면 골격 — 사용자 중간 검토

**Files:** `features/auth/LoginView.tsx`, `AuthGate.tsx`, `App.tsx`, `styles.css`, 기존 `design/AccessPreview.tsx`; 검사 `frontend/tests/oauth_login.test.mjs`.
**Consumes:** Task 1 공통 부품. **Produces:** 제품 LoginView와 동일 렌더링의 로그인 preview.

- [ ] App의 중복 전역 헤더·계정 줄을 화면별 헤더/계정 메뉴로 정리한다. 로그아웃 전 이탈 보호 이벤트와 본문 건너뛰기는 유지한다.
- [ ] 큰 제목·대표 사진·짧은 글귀·카카오 우선/Google 후순위 버튼을 배치한다. 활성 provider만 표시하며 기존 OAuth URL/returnTo/error 처리는 바꾸지 않는다.
- [ ] 로그인 후 동의 화면을 같은 재질로 적용한다. 미제공 프로필 사진은 사람 사진을 만들어 넣지 않고 이름 이니셜을 사용한다.
- [ ] 고정 사진은 ‘검토할 핵심 결정 3’대로 준비한다. 검토 전용 소재와 제품 소재의 상태를 명시한다.
- [ ] OAuth 기존 검사·빌드와 390/426px 실제 캡처를 확인한다. 사용자에게 원본/구현 비교를 제시해 공통 재질·사진·간격을 검토받고 승인 전 다음 화면 확산을 멈춘다.

### Task 3. 책장·업로드·진행 화면 적용

**Files:** `Bookshelf.tsx`, `AlbumCard.tsx`, `AlbumEditor.tsx`, `UploadPanel.tsx`, `UploadPhotoCard.tsx`, `GenerationProgress.tsx`, `PhotoStack.tsx`, `GenerationSteps.tsx`, feature CSS/preview.
**Consumes:** 승인된 Task 2 토큰·골격, 기존 API/훅. **Produces:** 실데이터 기반 세 화면.

- [ ] 책장은 2열 표지·오른쪽 상태 배지·제목/날짜/장수·더보기·하단 새 사진첩으로 구성한다. 빈 책장/페이지 추가 읽기/삭제 실패도 유지한다.
- [ ] 업로드는 사진 카드 위 번호·상태를 얹고 카드 아래 조작 메뉴를 둔다. 사진 추가와 업로드 실행 단계를 명확히 유지한다. 지원 형식/전처리/진행/실패/동일 요청 재시도는 기존 훅에 연결한다.
- [ ] 현재 날짜순/직접 정한 순서를 표시하고, 기존 앞으로/뒤로 이동을 제공한다. 아직 제공하지 않는 드래그 안내는 쓰지 않는다.
- [ ] 진행 화면에서 기존 album 상세 GET 및 서명 미디어 훅으로 최대 3장 미리보기를 표시한다. 미리보기 실패는 생성 polling을 막지 않는다.
- [ ] 단계는 실제 task 상태에서 도출한다: 사진 준비는 접수된 run 기준 완료, 사진첩 만들기는 caption/image_transform, 마무리는 optimize 기준. unknown/failed를 완료/진행 중으로 숨기지 않는다. 실제 completed_pages 진행률을 유지한다.
- [ ] 격리 local_fake 환경에서 빈/다수 앨범, 사진 1/6/50장, 검증 대기/실패, 순서 변경, 재시도/복구를 확인한다. 기존 업로드·generation/session 검사도 실행한다.

### Task 4. 한 장씩 글귀 검토와 감상

**Files:** `ReviewEditor.tsx`, `CaptionEditor.tsx`, `ThumbnailStrip.tsx`, `AlbumViewer.tsx`, `ViewerNavigation.tsx`, `BackgroundMusic.tsx` 표현 부분, feature CSS; 검사 `frontend/tests/review_navigation.test.mjs`.
**Consumes:** 기존 review drafts/save/publish/leave guard, SignedPhoto, BGM controller. **Produces:** ID 기반 선택 화면과 편집 UI.

- [ ] A 입력 → B 선택 → A 복귀 시 입력 유지, A 저장 응답이 B 입력을 덮지 않음, 다른 페이지 dirty/conflict도 publish 차단하는 회귀 검사를 먼저 작성한다.
- [ ] ReviewEditor에 activePageId만 추가한다. 초안 원장은 기존 페이지 ID별 map을 유지하고 사진 선택은 URL/history push 없이 수행한다.
- [ ] 큰 사진 아래 편집 패널·가로 썸네일·하단 완성 버튼을 배치한다. hidden 페이지의 미저장 상태를 썸네일에 표시하고 80자·빈 글귀·409 충돌·입력 버리기·완성 재시도를 유지한다.
- [ ] 감상은 사진 전체·하단 글귀/이전다음·상단 뒤로가기/BGM으로 구성한다. 제목·글귀 수정은 보조 메뉴에서 접근 가능하게 한다. 키보드/스와이프·URL 갱신·다음 장 prefetch는 보존한다.
- [ ] 음악 버튼은 swipe 대상 밖에 두고 이벤트 분리를 유지한다. 기존 music 검사를 실행하며 클릭 전 정지, 클릭 후 재생, 페이지 이동 간 유지, 이탈/숨김 시 정지를 확인한다.
- [ ] 화면 키보드 표시·긴 글귀·320px·저장 중 전환·브라우저 뒤로가기·완성 실패를 검증한다.

### Task 5. 통합 비교·검증·인계

**Files:** `frontend/design-preview/IMPLEMENTATION.md`, `frontend/design-preview/components.html`, `docs/검증계획.md` UI 결과 항목. Dockerfile은 새 frontend 검사 등록만 변경하며 다른 세션과 소유권 조율 후 수행한다.

- [ ] 제품 컴포넌트 기반 6개 화면과 파생 상태(동의/빈 책장/업로드 오류/unknown/저장 충돌)를 캡처한다. 생성/검토/감상은 같은 테스트 사진을 사용한다.
- [ ] 426px에서 원본 비교·overlay를 확인하고 위치/크기/여백 차이를 수정한다. 시안과 다르게 유지한 제품 정책 및 대표 사진 차이는 기록한다.
- [ ] `docker build --target frontend -t mori-ui-components:frontend .`로 타입·Vite·등록된 frontend 검사를 실행한다. 새 UI 검사는 기존 esbuild/Node 환경을 사용해 Dockerfile에 등록한다. `docker build --target runtime -t mori-ui-components:runtime .`와 `git diff --check`를 실행한다.
- [ ] 격리 runtime에서 로그인→동의→사진 업로드→가짜 생성→글귀 저장→완성→감상/BGM을 확인한다. 실제 OAuth/R2/OpenAI 실연동 성공으로 표현하지 않는다.
- [ ] 사용자가 제공 가능한 모바일 실기기에서 주소창/키보드/스크롤/음악을 확인한다. 미실행이면 별도 잔여 검증으로 표시한다.
- [ ] 변경 경계·제품/preview 의존성·보존된 상태/오류 흐름을 최종 검토하고 시각 결과·실행 명령·미검증 항목을 인계한다. 제품용 대표 사진이 미확정이면 해당 항목을 완료로 표시하지 않는다.

## 실행 방식 제안과 완료 조건

이 계획은 공통 스타일과 화면 조립의 의존성이 높으므로 **한 세션에서 순차 구현**을 기본으로 한다. 공통 CSS를 여러 작업자가 동시에 편집하지 않는다. 추가 에이전트 실행은 현재 계획에 포함하지 않는다.

최종 완료는 6개 제품 화면 적용, 공통 컴포넌트 미리보기, 검증 결과, 시안 대비 차이 목록이 모두 준비된 상태다. 첫 확인 지점은 Task 2의 로그인 비교 화면이다. 지금은 이 문서만 작성하며 사용자 계획 검토 전 제품 코드를 수정하지 않는다.

## 2026-10-18 실행 상태

사용자가 로그인 중간 결과를 확인하고 후속 진행을 승인했다. Task 1~4 제품 컴포넌트 적용과 Task 5의 빌드·로컬 E2E·25조합 DOM 폭 검사는 완료했다. 대표 사진·스크린샷 기반 최종 시각 비교·실기기·독립 리뷰는 미완료다. 세부 근거와 의도적 차이는 `frontend/design-preview/UI-COMPONENTS-PROGRESS.md` 최신 결과를 따른다. 체크박스 전체를 완료로 일괄 전환하지 않는다.
