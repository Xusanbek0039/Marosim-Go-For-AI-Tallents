"""Reels without ffprobe on the server: the file must still look like a video container.

Without ffprobe, `reels.prepare` used to check only the extension and size, so any file renamed to
.mp4 was accepted and published in the studio's portfolio. A system check also says so loudly.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from apps.studios import checks, reels
from tests.conftest import image_file

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01" + b"\x00" * 64


@pytest.fixture
def no_ffprobe(monkeypatch):
    monkeypatch.setattr(reels, "_probe", lambda path: None)


def poster():
    return image_file("poster.png", size=(360, 640))


@pytest.mark.parametrize("name,content", [("a.mp4", MP4), ("a.m4v", MP4), ("a.mov", MOV), ("a.webm", WEBM)])
def test_real_container_signatures_are_accepted(no_ffprobe, name, content):
    result = reels.prepare(SimpleUploadedFile(name, content, "video/mp4"), poster())
    assert result["video"].name.endswith(name[1:]) and result["duration"] == 0


@pytest.mark.parametrize(
    "name,content",
    [
        ("evil.mp4", b"<html><script>alert(1)</script></html>" + b" " * 64),
        ("a.webm", MP4),  # wrong container for the extension
        ("a.mp4", WEBM),
        ("tiny.mp4", b"\x00\x00"),
    ],
)
def test_non_video_content_is_rejected_without_ffprobe(no_ffprobe, name, content):
    with pytest.raises(ValidationError):
        reels.prepare(SimpleUploadedFile(name, content, "video/mp4"), poster())


def test_system_check_warns_when_ffprobe_is_missing(monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: None)
    warnings = checks.check_video_tools(app_configs=None)
    assert [w.id for w in warnings] == ["studios.W001"]


def test_system_check_is_silent_when_ffprobe_exists(monkeypatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert checks.check_video_tools(app_configs=None) == []
