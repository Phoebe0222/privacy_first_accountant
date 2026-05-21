import io
import pdfplumber
from PIL import Image


def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)[:6000]


def is_image_file(filename: str) -> bool:
    return filename.lower().split(".")[-1] in {"jpg", "jpeg", "png", "webp", "gif", "bmp"}


def is_pdf_file(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def normalise_image(file_bytes: bytes) -> bytes:
    """Convert any uploaded image to JPEG bytes for the vision model."""
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
