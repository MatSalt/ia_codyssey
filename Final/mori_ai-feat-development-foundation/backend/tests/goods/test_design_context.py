import pytest
from backend.goods_design.history import Revision, design_context
from backend.goods_design.prompt_profiles import build_prompt, catalog


def revisions():
    return [Revision('a', 's', None, '고양이'), Revision('b', 's', 'a', '빨간 모자'), Revision('c', 's', 'a', '파란 스카프')]


def test_selected_ancestor_branch_never_includes_sibling():
    assert design_context(revisions(), 'c', 's') == ('고양이', '파란 스카프')
    assert design_context(revisions(), 'b', 's') == ('고양이', '빨간 모자')
    assert design_context(revisions(), None, 's') == ()


def test_context_preserves_long_chain_in_chronological_order():
    rows = [Revision(str(i), 's', str(i-1) if i else None, f'수정{i}') for i in range(20)]
    assert design_context(rows, '19', 's') == tuple(f'수정{i}' for i in range(20))


@pytest.mark.parametrize('rows,selected', [
    ([Revision('a', 'other', None, 'private')], 'a'),
    ([Revision('a', 's', 'missing', 'a')], 'a'),
    ([Revision('a', 's', 'a', 'a')], 'a'),
    ([Revision('a', 's', 'b', 'a'), Revision('b', 's', 'a', 'b')], 'a'),
    ([Revision('a', 's', None, 'a'), Revision('a', 's', None, 'duplicate')], 'a'),
])
def test_invalid_context_fails_closed(rows, selected):
    with pytest.raises(ValueError):
        design_context(rows, selected, 's')


def test_prompt_uses_selected_branch_and_versions_settings():
    snapshot = build_prompt('book', '꽃 추가', design_context(revisions(), 'c', 's'), editing=True)
    assert '고양이' in snapshot.prompt and '파란 스카프' in snapshot.prompt
    assert '빨간 모자' not in snapshot.prompt
    assert snapshot.prompt.index('고양이') < snapshot.prompt.index('파란 스카프') < snapshot.prompt.index('꽃 추가')
    assert 'transparent' in snapshot.prompt and 'open book' in snapshot.prompt
    assert snapshot.version and snapshot.style_id == 'book'
    with pytest.raises(AttributeError):
        snapshot.prompt = 'changed'


def test_invalid_style_or_empty_request_cannot_silently_use_free_style():
    for style, request in [('unknown', 'cat'), ('free', '  '), ('photo', 'x'*3001)]:
        with pytest.raises(ValueError):
            build_prompt(style, request)


def test_catalog_is_public_metadata_without_provider_instructions():
    rows = catalog()
    assert {r['id'] for r in rows} == {'photo', 'illustration', 'cutout', 'badge', 'book', 'free'}
    assert all(set(r) == {'id', 'label', 'hint'} for r in rows)
