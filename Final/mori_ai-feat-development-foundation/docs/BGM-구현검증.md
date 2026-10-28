# BGM 구현·검증 — 2026-10-17

사용자가 제공한 `assets/audio/bgm.mp3`를 사진첩 배경음악으로 연결했다. 새로운 외부 서비스·SDK·migration은 없다. 기존 moriai 코드는 이식하지 않았다.

## 구현과 UI 인계

- 앱 공용 음원: `GET/HEAD /audio/bgm.mp3`, `audio/mpeg`, HTTP Range 지원. 사용자 미디어 디렉터리는 노출하지 않는다. 파일 변경을 반영하도록 cache 재검증을 요구한다.
- 기존 `Viewer.music` nullable 구조를 사용한다. 음원이 있으면 `mori-bgm-v1`, `/audio/bgm.mp3`, `사진첩 배경음악`을 제공하고 없으면 null이다. 샘플 응답도 실제 연결 형태로 갱신했다.
- `BackgroundMusic.tsx`는 `<BackgroundMusic key={albumId} music={data.music}/>` 형태로 사용한다. `AlbumViewer.tsx`의 기존 준비 중 문구만 교체했다. 같은 사진첩의 페이지를 넘겨도 음악이 끊기지 않고 사진첩 변경·뷰어 종료 시 정리한다.
- `musicPlayback.ts`가 재생 수명을 관리한다. 자동재생은 하지 않는다. 사용자 클릭 시작/끄기, loop, 기본 volume 0.35, `preload=none`, visibility hidden·pagehide·세션 만료·로그아웃 시 정지한다. 복귀 시 다시 켜기를 눌러야 한다.
- 지연된 play promise가 취소/이탈 후 완료돼도 재생하지 않는다. 재생 거부·음원 오류에는 재시도 안내를 표시하고 사진 감상은 유지한다. 제어 클릭/방향키는 사진 넘김에 전파하지 않는다.
- UI 세션은 `viewer-music`, `music-note`, `secondary`의 스타일·배치를 개선할 수 있다. lifecycle·null 처리·키보드/포인터 전파 방지는 보존한다. 공통 CSS는 총괄에서 수정하지 않았다.
- `Dockerfile`의 runtime/verification에 음원을 명시적으로 포함했다. BGM 상태 테스트를 frontend build 단계에 추가했다.

## 검증

- MP3 metadata: 140.042초, 44.1kHz, stereo, 4,481,358 bytes.
- frontend typecheck/build 및 상태 제어 7개 통과: 클릭 시작/끄기·반복, background/pagehide, 자동재개 없음, play 거부/미디어 오류, pending 취소/이탈, 세션 만료, listener 해제.
- 격리 PostgreSQL 포함 서버 44개 통과: 기존 뷰어·publish·소유권·미디어 URL 회귀, BGM Range/HEAD, 음원 없음·미등록 audio 경로의 404.
- 실제 모바일 Safari/Chrome에서의 청취·시스템 인터럽트·배경 전환 조합은 자동 시험으로 대체하지 않는다. 기기에서 마지막 확인이 필요하다.

## 사용 확인

로컬 QA 페이지를 새로고침하고 완성된 사진첩 감상 화면에서 ‘배경음악 켜기’를 누른다. 사진을 넘겨도 유지되는지, 끄기·책장으로 이동·다른 앱으로 전환하면 멈추는지 확인한다. 돌아왔을 때는 ‘배경음악 켜기’를 다시 눌러 시작한다.


정식 Dockerfile runtime 빌드 성공. frontend 전체 회귀63개(신규 BGM7개 포함)가 통과했고 ffmpeg 전체 MP3 디코딩 오류가 없었다. QA는 `mori-ai:bgm-runtime` 웹 이미지로 반영했으며 기존 DB/worker는 유지했다. 실제 모바일 청취 확인은 사용자에게 남긴다.
