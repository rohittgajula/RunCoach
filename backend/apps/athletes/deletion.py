"""Account deletion (docs/DEPLOY.md §2.5).

The database cascade from User removes every row. Files on disk do not cascade, so
they are collected first and removed after the rows are gone: FIT files, meal photos,
and the athlete's Garmin token directory (a live credential for their Garmin account).
"""

import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

logger = logging.getLogger(__name__)


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _athlete_paths(user: User) -> list[Path]:
    """Every file and directory on disk that belongs to this user."""
    from apps.diet.models import Meal
    from apps.ingest.models import RawFitFile

    athlete = getattr(user, "athlete", None)
    if athlete is None:
        return []
    media = Path(settings.MEDIA_ROOT)
    paths = [
        media / name
        for name in list(RawFitFile.objects.filter(athlete=athlete).values_list("file", flat=True))
        + list(Meal.objects.filter(athlete=athlete).exclude(photo="").exclude(photo=None)
               .values_list("photo", flat=True))
        if name
    ]
    # The per-athlete directories themselves (see fit_upload_path, meal_photo_path),
    # so files no row points at any more go too.
    paths += [media / "fit" / f"athlete_{athlete.pk}", media / "meals" / str(athlete.pk)]
    token_root = Path(settings.GARMIN_TOKEN_DIR)
    token_dir = Path(athlete.token_dir)
    if _inside(token_root, token_dir) and token_dir.resolve() != token_root.resolve():
        paths.append(token_dir)
    return [p for p in paths if _inside(media, p) or p == token_dir]


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        # Logged, not raised: the account is already gone, and a leftover file is
        # better reported than a half-finished deletion retried by the user.
        logger.exception("account deletion: could not remove %s", path)


def revoke_refresh_tokens(user: User) -> int:
    """Blacklist every outstanding refresh token, so no device stays signed in."""
    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        count += created
    return count


def delete_account(user: User) -> None:
    paths = _athlete_paths(user)
    with transaction.atomic():
        revoke_refresh_tokens(user)
        # OutstandingToken.user is SET_NULL, so the blacklist rows outlive the user.
        user.delete()
    for path in paths:
        _remove(path)
