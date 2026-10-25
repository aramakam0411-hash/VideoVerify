"""TikTok support uses the same bounded acquisition and local inspection."""
import shutil
import socket
from types import SimpleNamespace

import pytest

from videoverify.acquisition import Acquirer, canonical_url
from videoverify.core import InspectionError, Inspector
from videoverify.fetch_worker import validate_media_url


@pytest.mark.parametrize('host', ['www.tiktok.com', 'tiktok.com', 'm.tiktok.com'])
def test_tiktok_canonical(host):
    assert canonical_url(f'https://{host}/@example.name/video/6748451240264420610/?tracking=secret') == (
        'https://www.tiktok.com/@example.name/video/6748451240264420610')


@pytest.mark.parametrize('url', [
    'https://vm.tiktok.com/abc/', 'https://www.tiktok.com/t/abc/',
    'https://www.tiktok.com/@example', 'https://www.tiktok.com/@example/live',
    'https://www.tiktok.com/@example/photo/6748451240264420610',
    'https://www.tiktok.com.evil.test/@example/video/6748451240264420610',
    'https://user:password@www.tiktok.com/@example/video/6748451240264420610',
    'https://www.tiktok.com:443/@example/video/6748451240264420610',
    'https://www.tiktok.com/@example/video/6748451240264420610/extra',
])
def test_tiktok_rejects_other_inputs(url):
    with pytest.raises(InspectionError):
        canonical_url(url)


def test_tiktok_cdn_is_bounded(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    for domain in ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com'):
        validate_media_url(f'https://v16.{domain}/signed.mp4')
    for url in ('https://tiktokcdn.com.evil.test/video', 'https://tiktok.com/video',
                'http://v16.tiktokcdn.com/video', 'https://v16.tiktokcdn.com:443/video'):
        with pytest.raises(InspectionError):
            validate_media_url(url)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('10.0.0.1', 443))])
    with pytest.raises(InspectionError):
        validate_media_url('https://v16.tiktokcdn.com/video')


def test_tiktok_import_then_sequence(media, tmp_path, monkeypatch):
    monkeypatch.setattr('videoverify.acquisition.importlib.util.find_spec', lambda _: object())
    monkeypatch.setattr('videoverify.acquisition.shutil.disk_usage', lambda _: SimpleNamespace(free=10**10))
    import subprocess
    original = subprocess.run
    def worker(command, **kwargs):
        if 'videoverify.fetch_worker' not in command:
            return original(command, **kwargs)
        shutil.copyfile(media['tone'], command[4])
        return SimpleNamespace(returncode=0, stdout=b'{"ok":true}')
    monkeypatch.setattr('videoverify.acquisition.subprocess.run', worker)
    receipt = Acquirer(tmp_path/'imports').fetch('https://www.tiktok.com/@example/video/6748451240264420610')
    result = Inspector([tmp_path/'imports'], tmp_path/'frames').inspect(receipt['video_path'], 1.3)
    assert result['frame']['frame_index'] == 13
    assert receipt['access'] == 'public_without_account'
