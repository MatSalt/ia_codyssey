# NULL;SPACE 브랜드 광고 스토리보드 초안

---

## 브랜드 아이덴티티

| 항목 | 내용 |
|------|------|
| **브랜드명** | NULL;SPACE |
| **카테고리** | 1인 개발자·프리랜서 전용 카페 |
| **타겟** | MZ 세대 개발자, 게이머, 프리랜서 |
| **톤앤매너** | 터미널 감성 + 글리치 / 다크·쿨·엣지 |
| **USP** | "코드를 짜는 사람을 위해 설계된 공간" — 집중 환경, 개발자 감성 인테리어, 무한 리필 카페인 |
| **광고 목적** | 브랜드 인지도 상승 |
| **핵심 메시지** | "예외는 없다. 오직 코드와 커피만." |

> **메시지 의도**: "예외(Exception)"는 프로그래밍 용어이자 일반어. 개발자에게는 즉각 인식되는 이스터에그, 일반인에게는 "흔들림 없는 공간"으로 읽힘.

---

## 씬 구성 (총 3씬 / 10초 이내)

---

### 씬 1 — BOOT (0~3초)

| 필드 | 내용 |
|------|------|
| **씬 길이** | 3초 |
| **목표 메시지** | "이 광고가 개발자를 위한 것임을 0.5초 안에 각인" |
| **화면 구성** | 완전한 검정 화면 / 초록 모노스페이스 폰트로 코드 비(rain)처럼 흘러내림 / 중앙에 커서(█) 깜박임 / 텍스트 없음 |
| **내레이션** | "예외 처리 없이 살아온 당신에게," |
| **사용 도구** | 이미지: GPT (DALL-E 3) — 터미널 코드 비주얼 생성 |
| | 비디오: Google Flow — 정지 이미지에 코드 흐르는 모션 적용 |
| | 오디오: 기계식 키보드 타이핑 효과음 (Suno 생성) |
| **입력 프롬프트** | 아래 상세 프롬프트 참고 |
| **출력 결과 요약** | 검정+초록 코드 비주얼, 터미널 감성 강한 키비주얼 확보 |
| **결과 파일명** | `scene01_terminal.png` / `scene01_motion.mp4` / `scene01_sfx.wav` |

**씬 1 이미지 프롬프트 (GPT / DALL-E 3용)**

> **맥락**: NULL;SPACE는 1인 개발자·프리랜서를 위한 카페 브랜드. 광고 첫 3초로, 브랜드 텍스트 없이 "개발자를 위한 공간"임을 시각적으로 각인하는 순수 분위기 컷. 전체 광고의 색상 팔레트는 #0a0a0a (거의 순수 검정) + #00ff88 (인광 초록) 두 가지로 고정.

```
A cinematic still image of a pure black screen completely filled with cascading 
bright phosphor-green monospace code characters, resembling a terminal matrix rain 
effect. The characters vary in brightness and blur at different depths, creating a 
convincing sense of vertical motion and depth of field. 

At the exact center of the frame, a single solid block cursor (█) glows with sharp 
focus and slightly brighter green than the surrounding characters, drawing the eye. 

The entire color palette is strictly limited to near-black (#0a0a0a) background and 
phosphor green (#00ff88) characters — no other colors, no gradients, no warm tones. 
No people, no objects, no UI elements, no brand text. 

The mood must feel cold, hyper-focused, and intense — like staring into a live 
terminal session at 3am with the room lights off. 

Cinematic quality, 16:9 aspect ratio, photorealistic rendering style.
```

**씬 1 동영상 프롬프트 (Google Flow용)**

> **맥락**: 이미 생성된 씬 1 이미지(터미널 코드 비)를 입력으로 사용. 모션만 기술 — 장면 구성은 이미지가 담당.

```
Duration: 3 seconds.

Green code characters cascade continuously downward, 
like a steady rainfall across the entire frame. 
The central block cursor blinks slowly at a 1-second interval. 
Camera is completely still. Smooth, looping motion. 
Atmosphere: cold, hypnotic.

Audio: mechanical keyboard typing sounds as ambient background. 
A calm, cold, low-pitched Korean male voice narrates slowly:
"예외 처리 없이 살아온 당신에게,"
Voice tone: dry, emotionless, like a system reading aloud. 
No music yet — only typing sounds and voice.
```

---

### 씬 2 — TRANSFORM (3~7초)

| 필드 | 내용 |
|------|------|
| **씬 길이** | 4초 |
| **목표 메시지** | "코드가 커피로 변환되는 순간 — 브랜드 세계관 충격 전달" |
| **화면 구성** | 코드 비가 점점 커피잔 실루엣으로 수렴 / 글리치 효과로 전환 / 카페 내부 공간(어두운 조명, 모니터 여러 대, 혼자 앉은 실루엣) 등장 / 텍스트 없음 |
| **내레이션** | "드디어, 당신만의 공간이 실행됩니다." |
| **사용 도구** | 이미지: GPT (DALL-E 3) — 카페 내부 + 코드→커피 변환 장면 생성 |
| | 비디오: Google Flow — 글리치 전환 효과 포함 모션 |
| | 오디오: Suno — 로파이 비트 BGM (타이핑 소리 지속) |
| **입력 프롬프트** | 아래 상세 프롬프트 참고 |
| **출력 결과 요약** | 코드→커피 전환 장면, 1인 개발자 카페 분위기 확보 |
| **결과 파일명** | `scene02_transform.png` / `scene02_motion.mp4` |

**씬 2 이미지 프롬프트 (GPT / DALL-E 3용)**

> **맥락**: 광고의 핵심 전환 장면(3~7초). "코드를 마시는 사람들을 위한 카페"라는 브랜드 세계관을 한 장에 표현. 씬 1의 터미널 감성을 유지하면서 카페 공간이 등장하는 브릿지 역할. 브랜드 텍스트 없음 — 편집 단계에서 삽입.

```
A dramatic cinematic still image showing a visual transformation: hundreds of bright 
phosphor-green terminal code characters (matrix-style cascade) are flowing downward 
from the top of the frame and converging, pooling together to form the perfect 
silhouette of a steaming coffee cup at the center. The coffee cup shape is constructed 
entirely from densely packed glowing green code — no solid fill, just code forming 
the outline and volume.

Behind and around the coffee cup, a moody dark cafe interior is partially visible: 
three or four large monitor screens emit a soft blue-green glow from the background, 
a single human figure is silhouetted in the distance against the monitors (no face 
visible, just a dark outline), industrial-minimal dark furniture, concrete walls. 

The edges of the image have a subtle digital glitch distortion — horizontal scanline 
tears and slight chromatic aberration — as if reality is being recompiled. 

Color palette: near-black background, phosphor green (#00ff88) code, soft cyan-blue 
monitor glow as the only accent. No warm tones, no white, no brand text.

Cinematic composition, 16:9 aspect ratio, high detail.
```

**씬 2 동영상 프롬프트 (Google Flow용)**

> **맥락**: 씬 2 이미지를 입력으로 사용. 코드가 커피잔으로 수렴하고 카페 공간이 드러나는 핵심 전환 모션 기술.

```
Duration: 4 seconds.

The code streams slow and converge inward toward the coffee cup 
silhouette at the center, as if being magnetically pulled. 
As they converge, strong digital glitch effects fire — 
sharp horizontal screen tears, RGB channel split, 
and brief chromatic aberration across the frame. 
The cafe background sharpens and becomes more defined. 
Subtle camera push-in toward the coffee cup. Speed: slow to medium.

Audio: typing sounds fade out and a low-fi beat fades in softly. 
A calm, cold, low-pitched Korean male voice narrates:
"드디어, 당신만의 공간이 실행됩니다."
Voice tone: same dry, system-like delivery as scene 1. 
Glitch sound effect fires briefly in sync with the visual glitch.
```

#### 프롬프트 수정 전/후 기록

| 구분 | 내용 |
|------|------|
| **수정 전 프롬프트** | `A coffee shop with a programmer working on a laptop, computers around, cozy atmosphere` |
| **수정 전 문제** | 일반적인 밝은 카페 이미지 생성, 터미널/개발자 감성 전혀 없음. NULL;SPACE만의 세계관과 완전히 불일치 |
| **수정 후 프롬프트** | 위 상세 프롬프트 |
| **수정 이유** | "코드가 커피로 변환된다"는 브랜드 핵심 은유를 시각화하기 위해 코드→커피잔 실루엣 수렴 모티프를 명시. 다크 카페 환경과 글리치 효과를 구체적으로 기술하여 차별화된 세계관 확보 |
| **결과 변화** | 터미널 감성과 카페 공간이 결합된 독창적 비주얼로 개선, 타 카페 광고와 즉각 구분 가능 |

---

### 씬 3 — LOGO OUT (7~10초)

| 필드 | 내용 |
|------|------|
| **씬 길이** | 3초 |
| **목표 메시지** | "NULL;SPACE = 개발자 카페" 브랜드명 각인 |
| **화면 구성** | 검정 배경 / 중앙에 `NULL;SPACE` 로고 타이핑 효과로 등장 (커서 깜박임) / 하단에 슬로건 페이드인 / 우측 하단 CTA 텍스트 |
| **내레이션** | "예외는 없다. 오직 코드와 커피만." |
| **사용 도구** | 이미지: GPT (DALL-E 3) — 로고 비주얼 배경 생성 |
| | 비디오: Google Flow — 타이핑 효과 모션 |
| | 오디오: ElevenLabs — 한국어 나레이션 TTS (낮고 차가운 톤) |
| **입력 프롬프트** | 아래 상세 프롬프트 참고 |
| **출력 결과 요약** | 로고 등장 배경 이미지, 브랜드 각인 컷 확보 |
| **결과 파일명** | `scene03_logo.png` / `scene03_motion.mp4` / `scene03_narration.mp3` |

**씬 3 이미지 프롬프트 (GPT / DALL-E 3용)**

> **맥락**: 광고 마지막 3초 브랜드 각인 컷. 이 이미지는 편집 단계에서 "NULL;SPACE" 텍스트와 슬로건, CTA를 오버레이하는 배경으로 사용됨. 따라서 중앙과 하단 중앙에 텍스트가 올라갈 공간이 확보되어야 하며, 배경 자체는 최대한 단순하고 강렬해야 함.

```
A minimalist cinematic background image designed for text overlay. The frame is 
dominated by a pure deep black background. At the center of the image, a soft 
radial glow of phosphor green (#00ff88) light emanates subtly outward, as if a 
terminal monitor is powered on just behind the camera — dim enough not to overpower 
text, but present enough to create atmosphere.

Across the lower third of the image, very faint horizontal scanlines add a CRT 
monitor texture to the darkness. A barely visible blinking block cursor (█) sits 
at the center of the frame, suggesting the screen is waiting for input.

The upper two-thirds of the frame must be clean near-black — no elements, no 
characters, no noise — to serve as a clear canvas for the brand logo "NULL;SPACE" 
to be placed in editing.

No text rendered in the image itself. No people, no objects, no warm colors. 
The mood is authoritative, cold, and precise — like a terminal that just finished 
executing a critical process.

Aspect ratio 16:9, high contrast, cinematic quality.
```

**씬 3 동영상 프롬프트 (Google Flow용)**

> **맥락**: 씬 3 이미지를 입력으로 사용. 브랜드 로고와 텍스트는 편집 단계에서 오버레이하므로, 배경 분위기를 살리는 최소한의 모션만 기술.

```
Duration: 3 seconds.

The green ambient glow at the center breathes slowly — gently brightening 
then dimming once. The CRT scanlines scroll upward at a very slow pace. 
Camera completely still. No sudden movement. Mood: quiet, authoritative.

At the center of the screen, the brand name "NULL;SPACE" appears letter by letter, 
as if being typed by a terminal — monospace font, phosphor green (#00ff88). 
After the brand name fully appears, the slogan fades in below it:
"예외는 없다. 오직 코드와 커피만."
Both texts remain on screen until the clip ends.

Audio: low-fi beat fades to silence as the brand name appears.
A calm, cold, low-pitched Korean male voice narrates with finality:
"예외는 없다. 오직 코드와 커피만."
Voice tone: slightly slower and more deliberate than previous scenes —
this is the line that must be remembered. Ends in complete silence.
```

---

## 사용 도구 목록

| 카테고리 | 주 도구 | 선택 이유 | 대체 도구 |
|---------|--------|---------|---------|
| 이미지 생성 | GPT (DALL-E 3) | 자연어 프롬프트로 복잡한 합성 장면 표현 용이, 접근성 높음 | Runware (FLUX), Midjourney, Ideogram |
| 비디오·오디오·나레이션·편집 | Google Flow (Veo 3.1) | 영상·한국어 음성·효과음·BGM·편집을 단일 플랫폼에서 처리, 유료 플랜으로 전 기능 사용 가능 | Runway Gen-3, Kling, Pika |

---

## 최종 영상 목표 스펙

| 항목 | 값 |
|------|-----|
| 길이 | 10초 이내 |
| 해상도 | 1920×1080 (1080p) |
| 프레임레이트 | 30fps |
| 비디오 코덱 | H.264 |
| 오디오 코덱 | AAC |
| 파일명 | `NULLSPACE_brand_ad_v1.mp4` |

---

## 제작 시 주의사항

- **일관성**: 씬 1~3 모두 검정 배경 + 초록/네온 계열 컬러 팔레트 고정
- **크레딧 절약**: GPT에서 이미지 확정 후 Google Flow 변환 진행
- **글리치 효과**: CapCut 내장 글리치 템플릿으로 씬 전환 처리
- **나레이션 톤**: ElevenLabs에서 낮고 건조한 남성 or 여성 목소리 선택 (감정 최소화)
