# 책장 디자인 검토 — revision 2

기준 e09cfe7. 제품 경로·API·BGM·공통 DTO·의존성 변경 없음.

최신 원본: 사용자 02-bookshelf.png (2026-10-17 16:40), SHA256 `5b5a5b46dbdb2e19a76c84bc72f13c791686ff00439c2f03ef052826dd12282b`.
기존 2화면 합본에서 단일 책장으로 바뀜. 빈 책장은 기존 구조를 새 스타일로 확장한 파생안이며 새 원본이 있는 것으로 주장하지 않음.

변경: warm white #FAF9F6, 유리 캡슐 CTA, 검정 글자, 17px 사진 모서리, 책등 제거, 완성 배지 숨김(보조기술 유지), 더보기 안의 샘플 삭제 버튼. 320/390/430/데스크톱 너비 선택 가능.

원본: 총괄 checkout에서 읽기 전용 복사. 사진은 시안의 일부를 CSS viewport로 표시하며 별도 이미지 편집 없음. 실제 데이터나 API 요청 없음.
공식 근거: apple-token-reference.json. 34/41 제목·17/22 헤드라인·13/18 Footnote 확인. SF Pro 파일 없이 시스템 폰트 사용.
유리 색·흐림·테두리·그림자·간격은 사용자 새 시안에 대응한 CSS 제안. Apple 네이티브 Liquid Glass와 동일하지 않음. 투명도 감소/대비 증가/blur 미지원 fallback 포함.

실행(저장소 루트):
`docker build --target frontend -t mori-ui-bookshelf:preview .`
`docker run -d --name mori-ui-bookshelf-preview -p 127.0.0.1:18173:5173 mori-ui-bookshelf:preview npm run dev -- --port 5173`
검토: http://127.0.0.1:18173/design-preview/

검토용 화면이며 제품 Bookshelf.tsx에 아직 통합하지 않았다. 삭제·생성은 안내만 표시. 실서비스 E2E·모바일 실기기 검증은 수행하지 않았다.

검증: 타입 검사·프로덕션 빌드 통과, preview 진입점 번들 통과(정적 이미지 URL은 Vite 제공 경로로 external 처리). 320px 검토 틀과 실측 805px 넓은 틀 가로 넘침 없음, 805px에서 3열 확인. 더보기→샘플 삭제는 안내만 표시하며 앨범 4개 유지·메뉴 닫힘 확인. 실제 기기 검증은 아님.

## Revision 3 — 다른 화면 검토

`/design-preview/screens.html`: 로그인/동의, 업로드/순서, 생성/안전한 재개/unknown, 결과/편집, 감상/BGM 켜짐의 11개 상태. 모두 local state 시연. BGM을 포함한 실제 모듈을 import하거나 API를 호출하지 않는다. 사진은 사용자 제공 01/03/04/05/06 시안을 읽기 전용 복사해 CSS로 표시. 공통 DTO/의존성/제품 화면 변경 없음. 사용자 시안의 날짜순 드롭다운·드래그·자동 동의는 도입하지 않음.

Revision 3 검증: `npm run build`(타입 검사 포함), ScreensPreview 별도 esbuild 번들 통과. Orca 브라우저에서 11개 상태의 320px 틀 clientWidth/scrollWidth 모두 320으로 가로 넘침 없음. 동의 체크 후 진행 활성화, 사진 준비 상태 전환, 순서 이동, 미저장 글귀의 완성 차단·사진 이동 후 입력 보존·저장 후 완성 활성화 확인. 실제 API/BGM 동작 검증이 아닌 검토용 local state 검증이다. 이번 확장 화면의 Orca screenshot은 timeout으로 캡처하지 못했으며 최종 시각 비교와 실기기 검증은 남아 있다.
