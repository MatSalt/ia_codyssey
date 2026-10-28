"""Versioned goods prompts adapted from pilot fb5a3418. No model or paid call policy."""
from dataclasses import dataclass

PROFILE_VERSION = "goods-pilot-v1"

@dataclass(frozen=True)
class PromptSnapshot:
    version: str
    style_id: str
    prompt: str

_PROFILES = {
    'photo': ('사진형 액자', '사진을 작은 액자처럼', 'Keep the source as a photograph without changing faces or the photography style. Preserve the scene inside one clean rounded rectangle. Only outside that rectangle is transparent.'),
    'illustration': ('사진을 그림으로', '구도는 살리고 그림체만', 'Turn the reference photo into a warm polished illustration while keeping the people count, their composition and scene. Frame it in one rounded rectangle, with transparency only outside the frame.'),
    'cutout': ('인물·반려동물', '배경 없이 주인공만', 'Isolate the main people or pet from the reference, preserving its photographic appearance unless the customer asks for an illustrated style. Remove the surrounding scene. The silhouette follows the subject, with a truly transparent exterior and one connected printable shape.'),
    'badge': ('여행·문구', '상징물과 글자를 한 모양에', 'Create one cohesive souvenir badge using the requested location symbols and lettering. Design an original connected outline, with transparent space outside the badge. Use only lettering explicitly requested by the user.'),
    'book': ('추억을 펼친 책', '그림과 문구를 오픈북에', 'Create a flat print illustration shaped like a small open book. Put the reference people or scene on one page and requested lettering or symbols on the other. The printed book can have gentle dimensional shading. Outside the connected open-book silhouette is transparent.'),
    'free': ('자유롭게', '원하는 모양을 말로 설명', 'Choose an original cohesive printable silhouette appropriate to the customer request, without forcing a rectangular frame.'),
}


def catalog() -> list[dict[str, str]]:
    return [{"id": key, "label": value[0], "hint": value[1]} for key, value in _PROFILES.items()]


def build_prompt(style_id: str, request: str, context: tuple[str, ...] = (), *, editing: bool = False) -> PromptSnapshot:
    if style_id not in _PROFILES or not isinstance(request, str) or not request.strip() or len(request) > 3000:
        raise ValueError("Invalid style or design request")
    if any(not isinstance(item, str) for item in context):
        raise ValueError("Invalid design context")
    base = (
        "Create flat acrylic print artwork following the customer's reference images and request. "
        "Preserve requested people count and recognizable features. Produce one cohesive connected silhouette, "
        "all artwork fully visible. No keychain hardware, drilled holes, acrylic rim or product mockup background. "
        "Render requested Korean text exactly. The region OUTSIDE the design must have a truly transparent alpha background. "
        "Design approach: " + _PROFILES[style_id][2]
    )
    if editing:
        base += " The first image is the selected design to edit. Preserve everything except the requested changes. Other images are original references."
    if context:
        base += "\nEarlier instructions from the selected branch (current request takes precedence):\n" + "\n".join(context)
    base += "\nCurrent customer request: " + request.strip()
    return PromptSnapshot(PROFILE_VERSION, style_id, base)
