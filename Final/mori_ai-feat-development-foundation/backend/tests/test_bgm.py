from fastapi.testclient import TestClient
from backend.main import create_app


def test_bgm_supports_streaming_and_head(tmp_path,monkeypatch):
    from backend.albums import music
    path=tmp_path/'bgm.mp3';path.write_bytes(b'ID3'+bytes(range(64)))
    monkeypatch.setattr(music,'BGM_PATH',path)
    client=TestClient(create_app(static_dir=tmp_path))
    assert music.viewer_music()=={'track_id':'mori-bgm-v1','title':'사진첩 배경음악','url':'/audio/bgm.mp3'}
    response=client.get('/audio/bgm.mp3',headers={'Range':'bytes=0-9'})
    assert response.status_code==206 and response.content==path.read_bytes()[:10]
    assert response.headers['content-type']=='audio/mpeg'
    assert response.headers['content-range']=='bytes 0-9/67'
    response=client.head('/audio/bgm.mp3')
    assert response.status_code==200 and response.content==b''
    assert response.headers['content-length']=='67'


def test_missing_bgm_and_other_audio_paths_never_return_spa(tmp_path,monkeypatch):
    from backend.albums import music
    monkeypatch.setattr(music,'BGM_PATH',tmp_path/'missing.mp3')
    (tmp_path/'index.html').write_text('<html>SPA</html>')
    client=TestClient(create_app(static_dir=tmp_path))
    assert music.viewer_music() is None
    for path in ('/audio/bgm.mp3','/audio/other','/audio'):
        response=client.get(path)
        assert response.status_code==404
        assert 'text/html' not in response.headers['content-type']
