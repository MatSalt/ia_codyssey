# UI 컴포넌트 적용 — 후속 구현 결과

2026-10-18 로그인 중간 검토 승인 후 책장·업로드·진행·글귀 검토·감상에 적용했다. 브랜치 `jimchoi9/ui-components`, 기준 `b01d22e`. 아래 이전 기록은 1차 단계의 이력이다.

## 사용자 검토 상태

사용자가 실제 로컬 앱이 시안 비교 화면과 다르다고 확인했다. 공통 컴포넌트 적용과 기능 검사 결과는 시각적 일치 완료를 의미하지 않는다. 로그인 대표사진은 요청대로 목업을 유지하며, 화면별 배치·간격·부가 UI 차이의 재현과 수정은 미완료다. 이번 커밋은 현재 구현 상태를 저장하는 중간 커밋이다.

## 최신 결과

- 공통 토큰·UI/layout/media 컴포넌트를 제품과 미리보기에서 공유한다. feature별 AlbumCard, UploadPhotoCard, PhotoStack, GenerationSteps, CaptionEditor, ThumbnailStrip, ViewerNavigation을 추가했다.
- 책장 모바일2열·데스크톱3~4열, 사진 중심 업로드 카드, 실제 task 기반 진행 단계, 한 장 편집/썸네일, 감상 하단 글귀/페이지 이동을 적용했다.
- 사진 선택은 activePageId만 변경한다. 페이지별 draft/save/conflict/publish 원장과 이탈 보호는 기존 구현을 유지한다. 계정 메뉴는 책장에 있으며 다른 화면에서는 책장 이동을 통해 접근한다.
- backend/API/DTO/전처리/음악 재생 controller/의존성·lock/배포 설정 변경 없음. Dockerfile은 새 frontend 검사 등록만 변경했다.
- 사용자 후속 결정에 따라 제품용 로그인 대표 사진은 목업으로 유지한다. 미리보기의 시안 사진은 제품에 번들하지 않는다. 대표 사진 확보는 이번 적용의 선행 조건이 아니다.

## 실제 로컬 앱 후속 적용

- 사용자 요청에 따라 비교 화면의 공통 버튼·사진 프레임을 실제 앱에도 적용했다. 업로드 패널은 사진 목록 아래로 이동하고, 형식 안내·편집 도움말·삭제 관리 메뉴는 펼침 영역으로 정리했다.
- 실제 로컬 앱 18181의 web/worker를 최신 runtime으로 갱신했다. 개발 로그인·독립 DB/media와 기존 로컬 테스트 사진첩을 유지했다.
- 추가 확인: 새 초안의 사진 추가 패널이 목록 뒤에 위치하고 안내가 기본 접힘 상태임을 실제 브라우저에서 확인했다.
- 후속 빌드 로그: /tmp/mori-ui-parity-build.log. frontend 80 passed / 0 failed, TypeScript/Vite/runtime 빌드 및 diff --check 통과.

## 검증

- frontend 전체 **80 passed / 0 failed**, TypeScript·Vite·runtime 빌드 성공. 기존74 + 공통UI3 + 실제 ReviewEditor 상태회귀1 + 생성단계2.
- 실제 ReviewEditor 검사는 A 수정→B 이동/수정→A 복귀→A 저장 중 B 이동을 실행하여 입력 보존, A 저장 응답의 B 비간섭, 다른 페이지 미저장 시 완성 차단을 확인했다. 기존 목록 구현에서 실패를 확인한 후 적용했다.
- unknown/failed/cancelled 작업은 진행단계에서 확인 필요로 표시하며 optimize 대기를 임의로 시작/완료로 표시하지 않는다.
- 5개 화면 × 320/390/426/430/1064px =25조합 DOM 크기 검사에서 넘침0. 생성 장식 사진의320px 1px 넘침을 재배치해 수정했다. 미리보기 grid는 바깥 창이 아닌 container 폭을 기준으로 한다.
- 독립 실제 runtime E2E: alpha 개발 로그인→로컬 테스트 동의→빈 책장→초안→JPG/PNG fixture2장 선택·전처리·업로드·검증→순서 변경→가짜 생성→글귀 수정→다른 사진 이동/복귀 입력 보존→저장 전 완성 비활성→서버 저장→완성→감상.
- 음소거한 실제 audio: 최초 paused/preload none, 켜기 후 paused=false·페이지1유지, 다음 페이지 전환 중 재생 유지, 책장 이탈 시 paused=true. 청취·모바일 실기기 검증과 구분한다.
- 최종 빌드 `/tmp/mori-ui-verified-build.log`, 25조합 `/tmp/mori-ui-layout-final.json`. 공백 검사 통과.
- 자동 screenshot은 Orca 캡처 timeout으로 확보하지 못했다. 시각적 일치와 실제 모바일 Safari·키보드/터치 검증, 실제 OAuth/R2/OpenAI 회귀 검증은 미완료다. DOM 폭 검사와 가짜 AI 성공을 그 검증으로 대체하지 않는다.

## 검토용 실행 자원

- 비교: http://127.0.0.1:18180/design-preview/components.html (상단 화면 선택)
- 실제 로컬 앱: http://127.0.0.1:18181/ (개발 로그인·가짜 AI, fixture 결과 유지)
- preview 컨테이너 `mori-ui-components-preview`; runtime Compose project `mori-ui-components`, 독립 postgres/media volume.
- 환경 `/tmp/mori-ui-components.env`, 로컬 arm64 override `/tmp/mori-ui-platform.yaml`. 운영/QA 환경파일은 읽거나 복사하지 않았다. 서버 배포 파일은 변경하지 않았다.
- 커밋·push·병합·운영 배포 없음. 원본 checkout의 배포 자동화 변경도 그대로다.

## 남은 항목

사용자 시각 검토·실기기 검증, 최종 통합/커밋은 별도다. 제품용 대표 사진은 사용자 요청으로 목업 유지한다. 이번에는 공통 스타일 충돌과 상태/미디어 동작을 작성자가 검토했고 독립 에이전트 리뷰는 수행하지 않았다. 아직 모든 계획 항목이 완료됐다고 표시하지 않는다.

---

# UI components — 첫 검토 인계

기준 b01d22e, 브랜치 jimchoi9/ui-components, 경로 /Users/choijimin/orca/workspaces/mori_ai/ui-components.
사용자 승인 계획: docs/superpowers/plans/2026-10-18-apple-ui-components.md.

## 현재 구현

- 토큰, GlassButton/IconButton/GlassPanel, ScreenHeader/BottomActionBar, PhotoFrame/PhotoThumbnail을 분리했다.
- LoginView를 실제 AuthGate와 ComponentsPreview가 공유한다. OAuth 제공자 목록·로그인 URL·동의/세션 처리는 유지한다. 카카오를 먼저 표시한다.
- 독립 미리보기는 원본 옆 보기·overlay·320/390/426/430/1064 폭 선택·부품 상태를 제공한다.
- 대표 사진은 미리보기에서만 기존 시안의 사진 부분을 CSS viewport로 보여준다. 실제 AuthGate는 아직 중립 placeholder다. 제품 대표 사진 확정 전 로그인 최종 완료가 아니다.
- 검토 URL: http://127.0.0.1:18180/design-preview/components.html
- 전용 컨테이너 mori-ui-components-preview, 이미지 mori-ui-components:frontend, 포트127.0.0.1:18180. DB/외부 API/운영 환경파일을 사용하지 않는다.

## 확인 결과와 한계

- 기준 frontend 빌드/기존74검사 통과. 새 UI 검사3개 포함77검사와 TypeScript/Vite 빌드 통과.
- 신규 검사: 기본 action button의 submit 방지·명시 submit 보존/disabled, 아이콘 접근성 이름, 썸네일 aria-pressed.
- 신규 컴포넌트 부재에서 검사 실패 확인 후 구현. 로그 /tmp/mori-ui-red.log, /tmp/mori-ui-components-green.log, /tmp/mori-ui-login-build.log.
- 실제 Orca Chromium DOM 측정: 로그인 320/390/426/430/1064 폭에서 scrollWidth=clientWidth. 320폭 부품도 넘침 없음. 버튼 최소 폭44/높이44 이상, 긴 문구 줄바꿈 확인.
- DOM click으로 두 번째 썸네일 선택 시 aria-pressed가 false/true/false로 변함. native Orca click만으로는 변경되지 않아 물리 입력 실기기 검증은 별도로 남긴다.
- 원본 캡처/overlay를 제공하지만 자동 screenshot은 Orca Page.captureScreenshot timeout으로 확보하지 못했다. 시각적 일치나 모바일 실기기 성공을 주장하지 않는다.
- 런타임 빌드 기록: /tmp/mori-ui-runtime.log. 유료 API 호출·실제 OAuth 로그인·배포 없음.

## 결정 기록

- Ruling: 계획 Task2의 App 전체 계정 메뉴 재배치는 나머지 화면 적용 때 진행한다. 로그인 단계에서는 기존 헤더만 숨겨 검토 범위를 한정했다. 지금 변경하면 아직 검토하지 않은 책장/감상에도 영향을 주므로 미뤘다.
- 제품 사진 별도 확보 전 placeholder를 유지한다. 기존 시안 PNG를 제품 bundle에 넣지 않는다. 시안/계획만 새 워크트리에 복사했으며 원본과 SHA256을 대조했다.
- 현재는 승인 계획의 ‘로그인 비교 후 사용자 검토’ 지점이다. 동의 스타일/나머지 화면/앱 계정 메뉴와 최종 통합 검증은 아직 완료하지 않았다.
- 커밋/푸시/병합/배포 없음. 원래 checkout의 배포 자동화 변경은 수정하지 않았다.
