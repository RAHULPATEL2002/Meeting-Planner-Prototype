"""Avatar upload handling: validate, normalise, store, delete.

Threat model for a file upload endpoint (all of these are handled below):

1. **Huge files** — a client can stream gigabytes; ``Content-Length`` lies.
   We read in bounded chunks and abort as soon as the limit is exceeded.
2. **Content-type spoofing** — ``image/png`` in the header proves nothing.
   Pillow has to successfully *decode* the bytes or we reject them.
3. **Path traversal** — the client-supplied filename is never used. We generate
   a UUID name and a fixed extension.
4. **Stored payloads / metadata leaks** — the image is re-encoded, which drops
   EXIF (including GPS coordinates) and any appended polyglot payload.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.config import settings

#: Formats we are willing to decode. Anything else is rejected before decoding.
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

#: Everything is re-encoded to JPEG: one format to serve, no transparency
#: surprises, and small files at avatar resolution.
OUTPUT_SUFFIX = ".jpg"

_CHUNK_SIZE = 64 * 1024


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read at most ``limit`` bytes, raising 413 if the stream is longer."""
    buffer = bytearray()
    while chunk := await upload.read(_CHUNK_SIZE):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Avatar must be {limit // 1024} KB or smaller",
            )
    return bytes(buffer)


def _to_square(image: Image.Image, edge: int) -> Image.Image:
    """Centre-crop to a square, then resize to ``edge`` x ``edge``.

    Cropping before resizing avoids the squashed look you get from resizing a
    non-square image straight into a square box.
    """
    width, height = image.size
    shortest = min(width, height)
    left = (width - shortest) // 2
    top = (height - shortest) // 2
    cropped = image.crop((left, top, left + shortest, top + shortest))
    return cropped.resize((edge, edge), Image.Resampling.LANCZOS)


async def store_avatar(upload: UploadFile) -> str:
    """Validate and persist an uploaded avatar; return the stored filename."""
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type. Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    raw = await _read_limited(upload, settings.avatar_max_bytes)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        with Image.open(io.BytesIO(raw)) as image:
            # ``load()`` forces full decoding, so a truncated or malformed file
            # fails here rather than halfway through writing to disk.
            image.load()
            # Flatten alpha/palette onto white; JPEG has no alpha channel.
            if image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                converted = image.convert("RGBA")
                background.paste(converted, mask=converted.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
            squared = _to_square(image, settings.avatar_edge_px)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a readable image",
        ) from exc

    filename = f"{uuid.uuid4().hex}{OUTPUT_SUFFIX}"
    destination = settings.avatar_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    squared.save(destination, format="JPEG", quality=85, optimize=True)
    return filename


def delete_avatar(filename: str | None) -> None:
    """Remove a stored avatar, ignoring an already-missing file.

    Guards against a crafted filename escaping the avatar directory, in case a
    bad value ever reaches the database.
    """
    if not filename:
        return
    target = (settings.avatar_dir / filename).resolve()
    avatar_root = settings.avatar_dir.resolve()
    if avatar_root not in target.parents:
        return
    Path(target).unlink(missing_ok=True)
