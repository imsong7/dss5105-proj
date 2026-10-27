"""Image-only emails -> plain text, so the classifier treats them like any other email.

Everything for reading images lives in this one file:
  1. decide whether an email is "image only" (almost no text)
  2. fetch its INLINE images (file attachments are never opened)
  3. clean each image and read it with Tesseract
  4. put the text into Email.body

Needs the Tesseract program installed (see README). Without it the app still runs and
image-only emails are sorted from sender and subject, with a note in the UI."""
import csv
import hashlib
import io
import logging
import os
import shutil
import subprocess
from collections import OrderedDict
from io import BytesIO

from PIL import Image, ImageOps

from .models import Email
from .providers.base import EmailProvider
from .textutil import clean

log = logging.getLogger(__name__)

# ---- settings (override in .env) -------------------------------------------------
OCR_ENABLED = os.getenv("OCR_ENGINE", "auto").strip().lower() != "off"
OCR_LANG = os.getenv("OCR_LANG", "eng")  # e.g. eng+chi_sim
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
MIN_BODY_CHARS = int(os.getenv("OCR_MIN_BODY_CHARS", "100"))  # "image only" = less text than this
MAX_IMAGES = int(os.getenv("OCR_MAX_IMAGES", "3"))  # per email
MAX_IMAGE_BYTES = int(float(os.getenv("OCR_MAX_IMAGE_MB", "5")) * 1_000_000)

MIN_PIXELS = 10_000       # skips icons, logos and tracking pixels (about 100 x 100)
MIN_TEXT_CHARS = 10       # less than this counts as "no text found"
MIN_WORD_CONF = 40        # Tesseract words below this confidence are dropped
LOW_CONFIDENCE = 60       # below this average, the UI warns the label may be less reliable
MAX_SIDE, TARGET_WIDTH = 3500, 1200  # large images are shrunk, small ones enlarged
TIMEOUT_SECONDS = 90

WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


# ---- Tesseract -----------------------------------------------------------------
def find_tesseract() -> str | None:
    """Path from .env, then PATH, then the usual Windows install folders."""
    if TESSERACT_CMD and os.path.isfile(TESSERACT_CMD):
        return TESSERACT_CMD
    return shutil.which("tesseract") or next((p for p in WINDOWS_PATHS if os.path.isfile(p)), None)


def ocr_status() -> dict:
    """For the sidebar: is image reading switched off, ready, or missing Tesseract?"""
    if not OCR_ENABLED:
        return {"mode": "off", "ready": False}
    return {"mode": "on", "ready": find_tesseract() is not None}


def _prepare(data: bytes) -> bytes:
    """Any image -> clean grayscale PNG that Tesseract reads well."""
    with Image.open(BytesIO(data)) as img:
        img.seek(0)  # animated GIF/WebP: first frame only
        img = ImageOps.exif_transpose(img)  # phone photos stored sideways
        if img.mode in ("RGBA", "LA", "P"):  # transparent PNGs would turn black-on-black
            rgba = img.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, "white")
            canvas.paste(rgba, mask=rgba.split()[-1])
            img = canvas
        gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
        w, h = gray.size
        if max(w, h) > MAX_SIDE:
            scale = MAX_SIDE / max(w, h)
            gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        elif w < TARGET_WIDTH:
            scale = min(3.0, TARGET_WIDTH / w)
            gray = gray.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        out = BytesIO()
        gray.save(out, format="PNG")
        return out.getvalue()


def _run_tesseract(cmd: str, png: bytes, psm: int) -> tuple[str, float]:
    try:
        proc = subprocess.run(
            [cmd, "stdin", "stdout", "-l", OCR_LANG, "--psm", str(psm), "tsv"],
            input=png, capture_output=True, timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tesseract timed out on this image.") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip()[:300] or "Tesseract failed.")

    rows = csv.reader(io.StringIO(proc.stdout.decode("utf-8", errors="replace")), delimiter="\t", quoting=csv.QUOTE_NONE)
    next(rows, None)  # header
    lines: "OrderedDict[tuple, list[str]]" = OrderedDict()
    confs: list[float] = []
    for row in rows:
        if len(row) < 12 or row[0] != "5":  # level 5 = one word
            continue
        word = row[11].strip()
        try:
            conf = float(row[10])
        except ValueError:
            continue
        if word and conf >= MIN_WORD_CONF:
            lines.setdefault((row[2], row[3], row[4]), []).append(word)  # block, paragraph, line
            confs.append(conf)
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, (sum(confs) / len(confs) if confs else 0.0)


def read_image(cmd: str, data: bytes) -> tuple[str, float]:
    """Text and average confidence (0-100) found in one image."""
    png = _prepare(data)
    text, conf = _run_tesseract(cmd, png, psm=3)  # automatic page layout
    if len(text) < 15:  # posters and flyers: scattered text reads better in sparse mode
        text2, conf2 = _run_tesseract(cmd, png, psm=11)
        if len(text2) > len(text):
            text, conf = text2, conf2
    return text, conf


# ---- the pipeline step -----------------------------------------------------------
def prepare_text(email: Email, provider: EmailProvider) -> Email:
    """Call once per fetched email, before classifying. Never raises for a bad image:
    problems go into email.ocr_notes and are shown in the UI."""
    text = (email.body or "").strip()
    email.text_source = "body" if text else "empty"
    if not OCR_ENABLED or len(text) >= MIN_BODY_CHARS:
        return email  # a normal email: nothing to do, no extra requests

    cmd = find_tesseract()
    if not cmd:
        if not text:
            email.ocr_notes.append("This email has no readable text and Tesseract is not installed, so its images were not read.")
        return email

    images = provider.fetch_images(email, max_images=MAX_IMAGES * 2, max_bytes=MAX_IMAGE_BYTES)
    if not images:
        if not text:
            email.ocr_notes.append(
                "No readable text and no inline images. The email may rely on images hosted online, "
                "which are not downloaded. Sorted from sender and subject only."
            )
        return email

    chunks: list[str] = []
    confidences: list[float] = []
    seen: set[str] = set()
    for img in images:
        if len(chunks) >= MAX_IMAGES:
            break
        digest = hashlib.sha1(img.data).hexdigest()
        if digest in seen:  # the same logo repeated in a signature
            continue
        seen.add(digest)
        if len(img.data) > MAX_IMAGE_BYTES:
            email.ocr_notes.append(f"Skipped {img.name}: file is too large.")
            continue
        try:
            with Image.open(BytesIO(img.data)) as probe:
                w, h = probe.size
        except Exception:
            email.ocr_notes.append(f"Could not open image {img.name}.")
            continue
        if w * h < MIN_PIXELS:  # icon, logo or tracking pixel
            continue
        try:
            found, conf = read_image(cmd, img.data)
        except Exception as exc:
            log.warning("OCR failed for %s: %s", img.name, exc)
            email.ocr_notes.append(f"Could not read {img.name}: {exc}")
            continue
        if len(found.strip()) < MIN_TEXT_CHARS:
            email.ocr_notes.append(f"No readable text found in {img.name}.")
            continue
        chunks.append(f"[Text read from image '{img.name}' by OCR, may contain errors]\n{found.strip()}")
        confidences.append(conf)

    if chunks:
        email.body = (text + "\n\n" if text else "") + "\n\n".join(chunks)
        email.text_source = "body+ocr" if text else "ocr"
        email.ocr_confidence = round(sum(confidences) / len(confidences), 1)
        if not email.preview:
            email.preview = clean(chunks[0].split("\n", 1)[-1]).replace("\n", " ")[:200]
        if email.ocr_confidence < LOW_CONFIDENCE:
            email.ocr_notes.append(
                f"Text from the image was hard to read ({email.ocr_confidence:.0f}% confidence), so this label may be less reliable."
            )
    elif not text:
        email.ocr_notes.append("Nothing readable was found, so this was sorted from sender and subject only.")

    email.images = []  # free the image bytes
    return email
