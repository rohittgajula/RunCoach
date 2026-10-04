"""docs/DEPLOY.md §2.4: meal photos behind signed, expiring URLs."""

import io
import time
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.diet.media import signed_url, verify


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()
    return settings.MEDIA_ROOT


def jpeg() -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "orange").save(buf, "JPEG")
    return SimpleUploadedFile("lunch.jpg", buf.getvalue(), content_type="image/jpeg")


def upload(api) -> str:
    r = api.post("/api/diet/meals/", {
        "meal_type": "lunch", "description": "dal rice", "items": "[]", "photo": jpeg(),
    }, format="multipart")
    assert r.status_code == 201, r.content
    return r.json()["photo_url"]


def split(url):
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    return parsed.path, q["exp"][0], q["sig"][0]


@pytest.mark.django_db
def test_photo_url_is_signed_and_works_without_auth(api, client):
    url = upload(api)
    assert url.startswith("/api/media/signed/meals/")
    response = client.get(url)  # anonymous, like an <img> tag
    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"].startswith("private, max-age=")
    assert b"".join(response.streaming_content)[:2] == b"\xff\xd8"


@pytest.mark.django_db
def test_expired_url_is_refused(api, client, monkeypatch):
    url = upload(api)
    path, exp, _ = split(url)
    monkeypatch.setattr(time, "time", lambda: int(exp) + 1)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_tampered_urls_are_refused(api, other_api, client):
    url = upload(api)
    other = upload(other_api)
    path, exp, sig = split(url)
    other_path, _, _ = split(other)
    # Later expiry, wrong signature, someone else's path with my signature.
    assert client.get(f"{path}?exp={int(exp) + 3600}&sig={sig}").status_code == 404
    assert client.get(f"{path}?exp={exp}&sig={'0' * 64}").status_code == 404
    assert client.get(f"{other_path}?exp={exp}&sig={sig}").status_code == 404
    assert client.get(path).status_code == 404


def test_traversal_and_foreign_roots_never_sign_or_verify():
    for bad in ["../secret", "meals/../../etc/passwd", "/etc/passwd", "fit/athlete_1/x.fit",
                "meals//x.jpg", "meals/./x.jpg", "meals\\..\\x"]:
        assert signed_url(bad) is None, bad
        assert verify(bad, str(int(time.time()) + 60), "0" * 64) is None, bad


@pytest.mark.django_db
def test_symlink_out_of_media_root_is_refused(client, media_root, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("nope")
    (media_root / "meals").mkdir()
    (media_root / "meals" / "evil.jpg").symlink_to(secret)
    assert client.get(signed_url("meals/evil.jpg")).status_code == 404


@pytest.mark.django_db
def test_missing_file_is_404(client):
    assert client.get(signed_url("meals/1/nothing.jpg")).status_code == 404


def test_url_expires_after_the_configured_ttl(settings):
    settings.SIGNED_MEDIA_TTL_SEC = 3600
    _, exp, sig = split(signed_url("meals/1/a.jpg", now=1_000_000))
    assert int(exp) == 1_003_600
    assert verify("meals/1/a.jpg", exp, sig, now=1_003_599) == "meals/1/a.jpg"
    assert verify("meals/1/a.jpg", exp, sig, now=1_003_601) is None
