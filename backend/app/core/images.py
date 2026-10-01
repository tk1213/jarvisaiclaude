"""Pictures sent with a request (a business card, an order with the customer's address).

Every picture is decoded and re-encoded here: that checks it really is an image, and shrinking it to
MAX_SIDE pixels keeps it readable for names and addresses while costing far fewer tokens than a phone photo.
"""

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1024
MAX_IMAGES = 4
MAX_BYTES = 15 * 1024 * 1024  # before shrinking


class ImageError(ValueError):
    pass


def to_jpeg(data: bytes) -> str:
    """Base64 JPEG no larger than MAX_SIDE on its long side."""
    if len(data) > MAX_BYTES:
        raise ImageError("รูปใหญ่เกิน 15 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # phone photos: honour the rotation flag
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ImageError("เปิดรูปไม่ได้ ไฟล์อาจไม่ใช่รูปภาพ") from e
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    return base64.b64encode(out.getvalue()).decode()


def from_base64(text: str) -> str:
    """A picture the dashboard sent (base64, optionally a data: URL), re-encoded the same way."""
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError as e:
        raise ImageError("ข้อมูลรูปไม่ถูกต้อง") from e
    return to_jpeg(raw)


def block(jpeg_b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg_b64}}
