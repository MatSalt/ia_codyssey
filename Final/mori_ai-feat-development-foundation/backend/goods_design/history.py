"""Branch-specific revision ancestry. Persistence must supply the complete chain."""
from dataclasses import dataclass
from collections.abc import Iterable


@dataclass(frozen=True)
class Revision:
    id: str
    session_id: str
    parent_id: str | None
    request: str


def design_context(revisions: Iterable[Revision], selected_id: str | None, session_id: str) -> tuple[str, ...]:
    if selected_id is None:
        return ()
    index: dict[str, Revision] = {}
    for revision in revisions:
        if revision.id in index:
            raise ValueError('Duplicate revision')
        index[revision.id] = revision
    seen: set[str] = set()
    requests: list[str] = []
    current = selected_id
    while current is not None:
        revision = index.get(current)
        if current in seen or revision is None or revision.session_id != session_id:
            raise ValueError('Invalid revision ancestry')
        seen.add(current)
        requests.append(revision.request)
        current = revision.parent_id
    return tuple(reversed(requests))
