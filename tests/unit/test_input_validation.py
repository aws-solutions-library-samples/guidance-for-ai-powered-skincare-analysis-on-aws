import asyncio
import base64
import io
import struct
import zlib
from unittest.mock import Mock

import pytest
from PIL import Image

import agentcore_entrypoint
from agents.input_validation import (
    MAX_ENCODED_IMAGE_BYTES, MAX_IMAGE_BYTES, ImageLimitError, decode_images, validate_payload,
)


def encoded_image(size=(64, 64), format="PNG", **kwargs):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=format, **kwargs)
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.parametrize("format", ["JPEG", "PNG", "GIF", "WEBP"])
def test_supported_static_images_are_fully_decoded_and_normalized(format):
    decoded = decode_images([encoded_image(format=format)])
    with Image.open(io.BytesIO(decoded[0])) as image:
        image.load()
        assert image.format == "JPEG"
        assert image.size == (64, 64)


def test_exif_and_appended_data_do_not_reach_model():
    exif = Image.Exif()
    exif[270] = "PRIVATE-METADATA"
    source = base64.b64decode(encoded_image(format="JPEG", exif=exif)) + b"APPENDED-INSTRUCTIONS"
    result = decode_images([base64.b64encode(source).decode()])[0]
    assert b"PRIVATE-METADATA" not in result and b"APPENDED-INSTRUCTIONS" not in result
    with Image.open(io.BytesIO(result)) as image:
        assert not image.getexif()


def test_maximum_dimension_and_count_are_allowed():
    assert len(decode_images([encoded_image(size=(2048, 2048))] * 3)) == 3


@pytest.mark.parametrize("images", [
    [], None, "not-a-list", [None], [""], ["not-base64!"],
    [base64.b64encode(b"\xff\xd8\xfftest").decode()],
    [base64.b64encode(b"\x89PNG\r\n\x1a\ntruncated").decode()],
])
def test_corrupt_or_invalid_inputs_are_rejected(images):
    with pytest.raises(ValueError):
        decode_images(images)


def test_encoded_size_checked_before_base64_allocation(monkeypatch):
    decoder = Mock(side_effect=AssertionError("Must reject before allocation"))
    monkeypatch.setattr(base64, "b64decode", decoder)
    with pytest.raises(ImageLimitError):
        decode_images(["A" * (MAX_ENCODED_IMAGE_BYTES + 1)])
    decoder.assert_not_called()


def test_decoded_size_boundary_checked_before_image_parser(monkeypatch):
    parser = Mock(side_effect=AssertionError("Must reject before parsing"))
    monkeypatch.setattr(Image, "open", parser)
    # Padding permits an encoded string within the character cap to decode too big.
    encoded = base64.b64encode(b"A" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ImageLimitError):
        decode_images([encoded])
    parser.assert_not_called()


def test_excess_count_checked_before_decoding(valid_image, monkeypatch):
    decoder = Mock(side_effect=AssertionError("Must reject before decoding"))
    monkeypatch.setattr(base64, "b64decode", decoder)
    with pytest.raises(ImageLimitError):
        decode_images([valid_image] * 4)
    decoder.assert_not_called()


def test_oversize_dimensions_rejected_before_pixel_load(monkeypatch):
    encoded = encoded_image(size=(2049, 2))
    loader = Mock(side_effect=AssertionError("Must reject before loading pixels"))
    monkeypatch.setattr(Image.Image, "load", loader)
    with pytest.raises(ImageLimitError):
        decode_images([encoded])
    loader.assert_not_called()


def test_decompression_bomb_header_rejected_without_allocating_pixels():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 2, 0, 0, 0))
    raw += chunk(b"IDAT", b"") + chunk(b"IEND", b"")
    with pytest.raises(ImageLimitError):
        decode_images([base64.b64encode(raw).decode()])


def test_animation_rejected():
    output = io.BytesIO()
    first = Image.new("RGB", (64, 64), "red")
    second = Image.new("RGB", (64, 64), "blue")
    first.save(output, format="GIF", save_all=True, append_images=[second], duration=100)
    with pytest.raises(ValueError, match="Animated"):
        decode_images([base64.b64encode(output.getvalue()).decode()])


def test_unrecognized_request_fields_are_rejected(valid_image):
    with pytest.raises(ValueError):
        validate_payload({"job_id": "test", "images": [valid_image], "prompt": "injected"})


def test_limit_error_does_not_construct_runtime_and_has_public_code(monkeypatch, valid_image):
    factory = Mock(side_effect=AssertionError("Must reject before model/AWS work"))
    monkeypatch.setattr(agentcore_entrypoint, "Orchestrator", factory)
    async def run():
        return [event async for event in agentcore_entrypoint.invoke(
            {"job_id": "oversize-reference", "images": [valid_image] * 4}, object()
        )]
    events = asyncio.run(run())
    assert len(events) == 1 and events[0]["code"] == "REQUEST_TOO_LARGE"
    assert events[0]["request_id"] == "oversize-reference"
    factory.assert_not_called()
