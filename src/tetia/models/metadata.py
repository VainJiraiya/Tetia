# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""The standard metadata of a media file, for the metadata panel.

read_metadata(path, kind) returns sections: [{"title": str, "rows": [{"label", "value"}]}].
Nothing here needs a dependency beyond Qt: JPEG EXIF is parsed by hand, video
comes from ffprobe (when installed), comics and EPUBs are zip files with an XML
file inside, and PDFs go through QtPdf (when this Qt has it). Whatever cannot
be read is left out rather than guessed, and a damaged file never raises.
"""
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import zipfile
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

MAX_XML_BYTES = 1_000_000      # the XML inside a comic or EPUB is small; never read a huge one
MAX_TEXT = 2000                # longest value shown (descriptions, prompts)
FFPROBE_TIMEOUT = 15


def _section(title: str, rows) -> dict:
    return {"title": title, "rows": [{"label": label, "value": str(value)} for label, value in rows if value not in (None, "")]}


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT].rstrip() + "…"


# ---- Formatting ----------------------------------------------------------------

def human_size(size: int) -> str:
    value, unit = float(size), "bytes"
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            break
        value /= 1024
    shown = f"{size:,} bytes" if unit == "bytes" else f"{value:.1f} {unit} ({size:,} bytes)"
    return shown


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _when(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


# ---- Every file --------------------------------------------------------------------

def file_section(path: str) -> dict:
    p = Path(path)
    try:
        info = p.stat()
    except OSError:
        return _section("File", [("Name", p.name), ("Location", str(p.parent)), ("Status", "The file is missing")])
    mime = ""
    try:
        from PySide6.QtCore import QMimeDatabase
        mime = QMimeDatabase().mimeTypeForFile(path).name()
    except Exception:       # noqa: BLE001 - the type is a nicety
        pass
    return _section("File", [
        ("Name", p.name),
        ("Location", str(p.parent)),
        ("Size", human_size(info.st_size)),
        ("Type", mime),
        ("Modified", _when(info.st_mtime)),
    ])


# ---- Images -----------------------------------------------------------------------------

def _ifd(data: bytes, offset: int, endian: str) -> dict:
    """One TIFF image file directory as {tag: value}. Out-of-range entries are skipped."""
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    out = {}
    try:
        (count,) = struct.unpack_from(endian + "H", data, offset)
        for i in range(min(count, 512)):
            tag, kind, n = struct.unpack_from(endian + "HHI", data, offset + 2 + i * 12)
            width = sizes.get(kind)
            if not width or n > 65536:
                continue
            total = width * n
            where = offset + 2 + i * 12 + 8
            if total > 4:
                (where,) = struct.unpack_from(endian + "I", data, where)
            raw = data[where:where + total]
            if len(raw) < total:
                continue
            if kind == 2:
                out[tag] = raw.split(b"\0")[0].decode("utf-8", "replace").strip()
            elif kind in (1, 7):
                out[tag] = raw
            elif kind in (3, 4, 9):
                code = {3: "H", 4: "I", 9: "i"}[kind]
                values = struct.unpack(endian + code * n, raw)
                out[tag] = values[0] if n == 1 else values
            else:                                   # rational (5) and signed rational (10)
                code = "II" if kind == 5 else "ii"
                numbers = struct.unpack(endian + code[0] * (2 * n), raw)
                pairs = [Fraction(numbers[j], numbers[j + 1]) if numbers[j + 1] else Fraction(0)
                         for j in range(0, 2 * n, 2)]
                out[tag] = pairs[0] if n == 1 else tuple(pairs)
    except (struct.error, IndexError):
        pass
    return out


def read_exif(path: str) -> dict:
    """{'ifd0': {...}, 'exif': {...}, 'gps': {...}} from a JPEG's Exif block ({} if none)."""
    try:
        with open(path, "rb") as f:
            head = f.read(262144)
    except OSError:
        return {}
    if head[:2] != b"\xff\xd8":
        return {}
    i = 2
    while i + 4 <= len(head) and head[i] == 0xFF:
        marker = head[i + 1]
        if marker in (0xDA, 0xD9):
            break
        (length,) = struct.unpack_from(">H", head, i + 2)
        segment = head[i + 4:i + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\0\0":
            tiff = segment[6:]
            endian = {b"II": "<", b"MM": ">"}.get(tiff[:2])
            if not endian:
                return {}
            try:
                (first,) = struct.unpack_from(endian + "I", tiff, 4)
            except struct.error:
                return {}
            ifd0 = _ifd(tiff, first, endian)
            result = {"ifd0": ifd0, "exif": {}, "gps": {}}
            if isinstance(ifd0.get(0x8769), int):
                result["exif"] = _ifd(tiff, ifd0[0x8769], endian)
            if isinstance(ifd0.get(0x8825), int):
                result["gps"] = _ifd(tiff, ifd0[0x8825], endian)
            return result
        i += 2 + length
    return {}


_ORIENTATION = {1: "Normal", 2: "Mirrored", 3: "Rotated 180°", 4: "Flipped vertically",
                5: "Mirrored, rotated 90° counter-clockwise", 6: "Rotated 90° clockwise",
                7: "Mirrored, rotated 90° clockwise", 8: "Rotated 90° counter-clockwise"}


def _exif_date(text) -> str:
    match = re.match(r"(\d{4}):(\d\d):(\d\d) (\d\d:\d\d:\d\d)", text) if isinstance(text, str) else None
    return f"{match[1]}-{match[2]}-{match[3]} {match[4]}" if match else ""


def _gps(gps: dict) -> str:
    try:
        def one(values, ref):
            deg, minutes, seconds = (float(v) for v in values)
            return deg + minutes / 60 + seconds / 3600, ref
        lat, lat_ref = one(gps[2], gps[1])
        lon, lon_ref = one(gps[4], gps[3])
        return f"{lat:.5f}° {lat_ref}, {lon:.5f}° {lon_ref}"
    except (KeyError, TypeError, ValueError):
        return ""


def exif_section(exif: dict):
    if not exif:
        return None
    ifd0, sub, gps = exif["ifd0"], exif["exif"], exif["gps"]
    make, model = ifd0.get(0x010F, ""), ifd0.get(0x0110, "")
    camera = model if model.startswith(make) else f"{make} {model}".strip()
    exposure = sub.get(0x829A)
    exposure_text = ""
    if isinstance(exposure, Fraction) and exposure > 0:
        exposure_text = f"1/{round(1 / exposure)} s" if exposure < 1 else f"{float(exposure):g} s"
    aperture = sub.get(0x829D)
    iso = sub.get(0x8827)
    focal = sub.get(0x920A)
    orientation = ifd0.get(0x0112)
    return _section("Camera", [
        ("Camera", camera),
        ("Lens", sub.get(0xA434, "")),
        ("Taken", _exif_date(sub.get(0x9003)) or _exif_date(ifd0.get(0x0132))),
        ("Exposure", exposure_text),
        ("Aperture", f"f/{float(aperture):.1f}" if isinstance(aperture, Fraction) and aperture > 0 else ""),
        ("ISO", iso if isinstance(iso, int) else ""),
        ("Focal length", f"{float(focal):g} mm" if isinstance(focal, Fraction) and focal > 0 else ""),
        ("Software", ifd0.get(0x0131, "")),
        ("Orientation", _ORIENTATION.get(orientation, "") if orientation != 1 else ""),
        ("GPS", _gps(gps)),
    ])


def image_sections(path: str) -> list:
    from PySide6.QtGui import QImageReader
    reader = QImageReader(path)
    size = reader.size()
    rows = []
    if size.isValid():
        megapixels = size.width() * size.height() / 1_000_000
        rows.append(("Dimensions", f"{size.width()} × {size.height()} ({megapixels:.1f} MP)"))
    rows.append(("Format", bytes(reader.format()).decode("ascii", "replace").upper()))
    sections = [_section("Image", rows)]
    exif = exif_section(read_exif(path))
    if exif and exif["rows"]:
        sections.append(exif)
    # PNG (and some other formats) carry text chunks: software, descriptions, prompts
    keys = reader.textKeys()[:20]
    text = [(key, _clip(reader.text(key))) for key in keys]
    if text:
        sections.append(_section("Embedded text", text))
    return sections


# ---- Video -------------------------------------------------------------------------------------

def _fps(rate: str) -> str:
    try:
        num, den = rate.split("/")
        value = float(num) / float(den)
        return f"{value:.2f}".rstrip("0").rstrip(".") + " fps" if value > 0 else ""
    except (ValueError, ZeroDivisionError, AttributeError):
        return ""


def _bitrate(value) -> str:
    try:
        bits = int(value)
    except (TypeError, ValueError):
        return ""
    return f"{bits / 1_000_000:.1f} Mb/s" if bits >= 1_000_000 else f"{round(bits / 1000)} kb/s"


def video_sections_from_probe(probe: dict) -> list:
    """Sections from ffprobe's JSON (kept apart so it is testable without ffprobe)."""
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    sections = []
    try:
        length = duration(float(fmt["duration"])) if fmt.get("duration") else ""
    except ValueError:
        length = ""
    sections.append(_section("Video", [
        ("Duration", length),
        ("Resolution", f"{video['width']} × {video['height']}" if video and "width" in video else ""),
        ("Frame rate", _fps(video.get("avg_frame_rate", "")) if video else ""),
        ("Codec", (video.get("codec_long_name") or video.get("codec_name", "")) if video else ""),
        ("Bit rate", _bitrate(video.get("bit_rate")) if video else ""),
    ]))
    if audio:
        first = audio[0]
        rate = first.get("sample_rate")
        sections.append(_section("Audio", [
            ("Codec", first.get("codec_long_name") or first.get("codec_name", "")),
            ("Channels", first.get("channel_layout") or first.get("channels", "")),
            ("Sample rate", f"{int(rate) / 1000:g} kHz" if rate else ""),
            ("Tracks", len(audio) if len(audio) > 1 else ""),
        ]))
    sections.append(_section("Container", [
        ("Format", fmt.get("format_long_name", "")),
        ("Overall bit rate", _bitrate(fmt.get("bit_rate"))),
        ("Title", _clip(tags.get("title", ""))),
        ("Created", tags.get("creation_time", "")[:19].replace("T", " ")),
        ("Subtitle tracks", len(subtitles) if subtitles else ""),
    ]))
    return [s for s in sections if s["rows"]]


def video_sections(path: str) -> list:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return [_section("Video", [("Details", "Install ffmpeg to see duration, codecs and resolution")])]
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT, check=False)
        probe = json.loads(result.stdout or "{}")
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logger.warning("ffprobe failed on %s: %s", path, e)
        return [_section("Video", [("Details", "The file could not be read")])]
    return video_sections_from_probe(probe) or [_section("Video", [("Details", "The file could not be read")])]


# ---- Comics and EPUBs (zip files) ------------------------------------------------------------

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        return b""
    return archive.read(name)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def comic_sections(path: str) -> list:
    if not zipfile.is_zipfile(path):
        return [_section("Comic", [("Archive", "Only .cbz (zip) archives are opened for details")])]
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            pages = [n for n in names if n.lower().endswith(_IMAGE_SUFFIXES) and not n.startswith("__MACOSX")]
            info_name = next((n for n in names if n.rsplit("/", 1)[-1].lower() == "comicinfo.xml"), None)
            xml = _read_member(archive, info_name) if info_name else b""
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return [_section("Comic", [("Archive", "The archive could not be read")])]
    sections = [_section("Comic", [("Pages", len(pages))])]
    if xml:
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            return sections
        field = {_local(child.tag): (child.text or "").strip() for child in root}
        year = "-".join(p for p in (field.get("Year", ""), field.get("Month", "").zfill(2) if field.get("Month") else "",
                                    field.get("Day", "").zfill(2) if field.get("Day") else "") if p)
        number = field.get("Number", "")
        count = field.get("Count", "")
        sections.append(_section("Details", [
            ("Title", field.get("Title", "")),
            ("Series", field.get("Series", "")),
            ("Number", f"{number} of {count}" if number and count else number),
            ("Volume", field.get("Volume", "")),
            ("Writer", field.get("Writer", "")),
            ("Penciller", field.get("Penciller", "")),
            ("Inker", field.get("Inker", "")),
            ("Colorist", field.get("Colorist", "")),
            ("Letterer", field.get("Letterer", "")),
            ("Cover artist", field.get("CoverArtist", "")),
            ("Translator", field.get("Translator", "")),
            ("Publisher", field.get("Publisher", "")),
            ("Published", year),
            ("Genre", field.get("Genre", "")),
            ("Tags", field.get("Tags", "")),
            ("Characters", field.get("Characters", "")),
            ("Language", field.get("LanguageISO", "")),
            ("Manga", field.get("Manga", "")),
            ("Age rating", field.get("AgeRating", "")),
            ("Summary", _clip(field.get("Summary", ""))),
            ("Web", field.get("Web", "")),
        ]))
    return sections


def epub_sections(path: str) -> list:
    try:
        with zipfile.ZipFile(path) as archive:
            container = ElementTree.fromstring(_read_member(archive, "META-INF/container.xml"))
            rootfile = next(el.get("full-path") for el in container.iter() if _local(el.tag) == "rootfile")
            opf = ElementTree.fromstring(_read_member(archive, rootfile))
    except (zipfile.BadZipFile, OSError, KeyError, StopIteration, ElementTree.ParseError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return [_section("Book", [("Details", "The EPUB could not be read")])]
    values = {}
    series = index = ""
    for el in opf.iter():
        name = _local(el.tag)
        text = (el.text or "").strip()
        if name == "meta":
            key = el.get("name") or el.get("property") or ""
            if key == "calibre:series":
                series = el.get("content", "")
            elif key == "calibre:series_index":
                index = el.get("content", "")
            elif key == "belongs-to-collection" and text and not series:
                series = text
        elif text and name in ("title", "creator", "publisher", "language", "date", "identifier",
                               "description", "subject", "rights"):
            values.setdefault(name, []).append(text)
    version = opf.get("version", "")
    first = lambda key: values.get(key, [""])[0]
    description = re.sub(r"<[^>]+>", " ", first("description"))
    return [_section("Book", [
        ("Title", first("title")),
        ("Author", ", ".join(values.get("creator", []))),
        ("Series", f"{series} #{index}" if series and index else series),
        ("Publisher", first("publisher")),
        ("Published", first("date")[:10]),
        ("Language", first("language")),
        ("Identifier", first("identifier")),
        ("Subjects", ", ".join(values.get("subject", []))),
        ("Description", _clip(description)),
        ("Rights", _clip(first("rights"))),
        ("Format", f"EPUB {version}" if version else "EPUB"),
    ])]


# ---- PDF --------------------------------------------------------------------------------------------

def pdf_sections(path: str) -> list:
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return [_section("Document", [("Details", "This Qt has no PDF support")])]
    document = QPdfDocument()
    if document.load(path) != QPdfDocument.Error.None_:
        return [_section("Document", [("Details", "The PDF could not be read (it may be encrypted)")])]

    from PySide6.QtCore import QDateTime

    def info(field):
        value = document.metaData(field)
        if isinstance(value, QDateTime):
            return value.toString("yyyy-MM-dd HH:mm") if value.isValid() else ""
        return str(value).strip() if value else ""

    size = ""
    if document.pageCount():
        page = document.pagePointSize(0)
        size = f"{page.width() * 25.4 / 72:.0f} × {page.height() * 25.4 / 72:.0f} mm"
    Field = QPdfDocument.MetaDataField
    sections = [_section("Document", [
        ("Title", info(Field.Title)),
        ("Author", info(Field.Author)),
        ("Subject", info(Field.Subject)),
        ("Keywords", info(Field.Keywords)),
        ("Pages", document.pageCount()),
        ("Page size", size),
        ("Created with", info(Field.Creator)),
        ("Producer", info(Field.Producer)),
        ("Created", info(Field.CreationDate)),
        ("Modified", info(Field.ModificationDate)),
    ])]
    document.close()
    return sections


# ---- Entry point -----------------------------------------------------------------------------------

def read_metadata(path: str, kind: str) -> list:
    """The sections of metadata for the file at `path`; kind is "image", "video", "comic" or "ebook"."""
    sections = [file_section(path)]
    if not os.path.isfile(path):
        return sections
    suffix = Path(path).suffix.lower()
    try:
        if kind == "image":
            sections += image_sections(path)
        elif kind == "video":
            sections += video_sections(path)
        elif kind == "comic":
            sections += comic_sections(path)
        elif kind == "ebook" and suffix == ".epub":
            sections += epub_sections(path)
        elif kind == "ebook" and suffix == ".pdf":
            sections += pdf_sections(path)
        elif kind == "ebook":
            sections.append(_section("Book", [("Details", f"Details of {suffix} files are not read")]))
    except Exception as e:      # noqa: BLE001 - a damaged file must never take the panel down
        logger.warning("Could not read the metadata of %s: %s", path, e)
    return [s for s in sections if s["rows"]]
