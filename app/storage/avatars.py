"""Profile pictures: decode, crop, resize and re-encode every upload server-side.

Nothing the user uploads is stored as-is. The image is opened with Pillow (which checks
the real format, not the filename or MIME type), limited in pixel count, rotated per its
EXIF orientation, center-cropped to a square, resized and saved as a fresh WebP. That
drops metadata such as GPS tags and any non-image payload hidden in the file.
"""
import io
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from app.storage.private_storage import PrivateStorageEngine

AVATAR_SIZE = 256
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_SOURCE_PIXELS = 40_000_000  # about 8000 x 5000; rejects decompression bombs


class AvatarError(ValueError):
    """The upload is not a usable profile picture; the message is safe to show."""


def process_avatar(data: bytes, max_bytes: int) -> bytes:
    if not data:
        raise AvatarError("The file is empty.")
    if len(data) > max_bytes:
        raise AvatarError(f"Profile pictures can be up to {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise AvatarError("Use a JPEG, PNG or WebP image.")
            if width * height > MAX_SOURCE_PIXELS:
                raise AvatarError("That image is too large. Use one under 40 megapixels.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            upright = ImageOps.exif_transpose(source)
            rgb = upright.convert("RGBA" if upright.mode in ("RGBA", "LA", "P") else "RGB")
            square = ImageOps.fit(rgb, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)
            out = io.BytesIO()
            square.save(out, format="WEBP", quality=86, method=4)
            return out.getvalue()
    except AvatarError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AvatarError("That file is not a readable image. Use a JPEG, PNG or WebP picture.") from exc


def store_avatar(storage: PrivateStorageEngine, user_id: str, webp: bytes) -> str:
    key = f"_avatars/{user_id}/{uuid.uuid4().hex}.webp"
    target = (storage.root_dir / key).resolve()
    target.relative_to(storage.root_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(webp)
    return key
