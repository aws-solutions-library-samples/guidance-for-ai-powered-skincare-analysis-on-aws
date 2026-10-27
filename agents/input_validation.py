"""Bound and decode untrusted images before constructing any agent or AWS client."""

import base64
import binascii
import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError
from .search.contracts import Preferences

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1024 * 1024
MAX_ENCODED_IMAGE_BYTES = 4 * ((MAX_IMAGE_BYTES + 2) // 3)
MAX_IMAGE_DIMENSION = 2048
MAX_IMAGE_PIXELS = MAX_IMAGE_DIMENSION**2
SUPPORTED_FORMATS = ("JPEG", "PNG", "GIF", "WEBP")


class ImageLimitError(ValueError):
    """A validly shaped request exceeds the published image budget."""


class PreferencesError(ValueError):
    """Malformed constraints are distinct from malformed photos."""


def validate_payload(payload: object) -> tuple[str, list[bytes]]:
    request_options(payload)
    job_id = payload["job_id"]
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise ValueError("Invalid request identifier")
    return job_id, decode_images(payload["images"])


def request_options(payload: object) -> tuple[int, Preferences]:
    if not isinstance(payload, dict) or not {"job_id", "images"} <= set(payload):
        raise ValueError("Expected job_id and images")
    version = payload.get("api_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported API version")
    allowed = {"job_id", "images"} if version == 1 else {"job_id", "images", "api_version", "preferences"}
    if set(payload) - allowed:
        raise ValueError("Unknown request fields")
    try:
        return version, Preferences.model_validate(payload.get("preferences", {}))
    except ValueError as exc:
        raise PreferencesError("Invalid ingredient preferences") from exc


def decode_images(images: object) -> list[bytes]:
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        if isinstance(images, list) and len(images) > MAX_IMAGES:
            raise ImageLimitError("Too many images")
        raise ValueError("Expected one to three images")
    decoded = []
    for encoded in images:
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("Encoded image is empty")
        if len(encoded) > MAX_ENCODED_IMAGE_BYTES:
            raise ImageLimitError("Encoded image is too large")
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw:
                raise ValueError("Decoded image is empty")
            if len(raw) > MAX_IMAGE_BYTES:
                raise ImageLimitError("Decoded image is too large")
            with Image.open(io.BytesIO(raw), formats=SUPPORTED_FORMATS) as image:
                width, height = image.size
                if (not 1 <= width <= MAX_IMAGE_DIMENSION
                        or not 1 <= height <= MAX_IMAGE_DIMENSION
                        or width * height > MAX_IMAGE_PIXELS):
                    raise ImageLimitError("Image dimensions exceed the limit")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not accepted")
                image.verify()
            # verify() alone does not decode JPEG pixels. Reopen and fully load.
            with Image.open(io.BytesIO(raw), formats=SUPPORTED_FORMATS) as image:
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGB")
                clean = io.BytesIO()
                # Normalize to JPEG and remove EXIF/location data and appended data.
                image.save(clean, format="JPEG", quality=90)
                normalized = clean.getvalue()
                if len(normalized) > MAX_IMAGE_BYTES:
                    raise ImageLimitError("Normalized image exceeds the limit")
                decoded.append(normalized)
        except Image.DecompressionBombError as error:
            raise ImageLimitError("Image dimensions exceed the limit") from error
        except (binascii.Error, OSError, UnidentifiedImageError) as error:
            raise ValueError("Invalid image") from error
    return decoded
