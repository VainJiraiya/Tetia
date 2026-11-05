# SPDX-FileCopyrightText: 2026 Tetia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import shutil
import struct
import subprocess
import zipfile

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtGui import QColor, QImage

from tetia.models import metadata
from tetia.models.database import get_database


def rows(sections, title):
    section = next(s for s in sections if s["title"] == title)
    return {r["label"]: r["value"] for r in section["rows"]}


# ---- formatting ------------------------------------------------------------------------

def test_human_size_and_duration():
    assert metadata.human_size(512) == "512 bytes"
    assert metadata.human_size(2_621_440) == "2.5 MB (2,621,440 bytes)"
    assert metadata.duration(75) == "1:15"
    assert metadata.duration(3725) == "1:02:05"


# ---- EXIF, built by hand -------------------------------------------------------------------

def _ifd(entries, base):
    """(directory bytes, data bytes) for entries [(tag, type, values)], little endian,
    with data that does not fit in 4 bytes placed after the directory."""
    sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}
    head = struct.pack("<H", len(entries))
    data = b""
    body = b""
    after = base + 2 + 12 * len(entries) + 4
    for tag, kind, values in entries:
        if kind == 2:
            raw, count = values + b"\0", len(values) + 1
        elif kind == 5:
            raw = b"".join(struct.pack("<II", n, d) for n, d in values)
            count = len(values)
        else:
            code = {1: "B", 3: "H", 4: "I"}[kind]
            raw = struct.pack("<" + code * len(values), *values)
            count = len(values)
        if len(raw) <= 4:
            field = raw.ljust(4, b"\0")
        else:
            field = struct.pack("<I", after + len(data))
            data += raw
        body += struct.pack("<HHI", tag, kind, count) + field
    return head + body + struct.pack("<I", 0), data


def exif_jpeg(path, with_gps=False):
    ifd0_probe = [(0x010F, 2, b"Canon"), (0x0110, 2, b"Canon EOS 5D"), (0x0112, 3, [6]),
                  (0x0131, 2, b"Tetia test"), (0x8769, 4, [0])] + ([(0x8825, 4, [0])] if with_gps else [])
    exif_entries = [(0x829A, 5, [(1, 250)]), (0x829D, 5, [(28, 10)]), (0x8827, 3, [400]),
                    (0x9003, 2, b"2024:05:17 14:30:05"), (0x920A, 5, [(85, 1)]), (0xA434, 2, b"EF85mm f/1.8")]
    gps_entries = [(1, 2, b"N"), (2, 5, [(48, 1), (51, 1), (24, 1)]),
                   (3, 2, b"E"), (4, 5, [(2, 1), (21, 1), (7, 1)])]
    ifd0_len = len(_ifd(ifd0_probe, 8)[0]) + len(_ifd(ifd0_probe, 8)[1])
    exif_at = 8 + ifd0_len
    exif_dir, exif_data = _ifd(exif_entries, exif_at)
    gps_at = exif_at + len(exif_dir) + len(exif_data)
    ifd0 = [(t, k, [exif_at] if t == 0x8769 else [gps_at] if t == 0x8825 else v) for t, k, v in ifd0_probe]
    d0, d0data = _ifd(ifd0, 8)
    tiff = b"II*\0" + struct.pack("<I", 8) + d0 + d0data + exif_dir + exif_data
    if with_gps:
        g, gdata = _ifd(gps_entries, gps_at)
        tiff += g + gdata
    segment = b"Exif\0\0" + tiff
    path.write_bytes(b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(segment) + 2) + segment + b"\xff\xd9")


def test_exif_is_read_from_a_jpeg(tmp_path):
    jpeg = tmp_path / "photo.jpg"
    exif_jpeg(jpeg, with_gps=True)
    camera = rows([metadata.exif_section(metadata.read_exif(str(jpeg)))], "Camera")
    assert camera["Camera"] == "Canon EOS 5D"            # the make is not repeated
    assert camera["Taken"] == "2024-05-17 14:30:05"
    assert camera["Exposure"] == "1/250 s"
    assert camera["Aperture"] == "f/2.8"
    assert camera["ISO"] == "400"
    assert camera["Focal length"] == "85 mm"
    assert camera["Lens"] == "EF85mm f/1.8"
    assert camera["Orientation"] == "Rotated 90° clockwise"
    assert camera["Software"] == "Tetia test"
    assert camera["GPS"] == "48.85667° N, 2.35194° E"


def test_exif_survives_garbage(tmp_path):
    for content in (b"", b"\xff\xd8", b"\xff\xd8\xff\xe1\x00\x08Exif\0\0", b"not a jpeg at all",
                    b"\xff\xd8\xff\xe1\x00\x20Exif\0\0II*\0\xff\xff\xff\xff" + b"\0" * 20):
        broken = tmp_path / "broken.jpg"
        broken.write_bytes(content)
        assert metadata.read_exif(str(broken)) in ({}, {"ifd0": {}, "exif": {}, "gps": {}})
    assert metadata.exif_section({}) is None


# ---- images --------------------------------------------------------------------------------------

def test_png_dimensions_and_text_chunks(tmp_path):
    image = QImage(40, 20, QImage.Format_RGB32)
    image.fill(QColor("red"))
    image.setText("parameters", "a very detailed prompt")
    path = tmp_path / "art.png"
    image.save(str(path))
    sections = metadata.read_metadata(str(path), "image")
    assert rows(sections, "Image")["Dimensions"].startswith("40 × 20")
    assert rows(sections, "Image")["Format"] == "PNG"
    assert rows(sections, "Embedded text")["parameters"] == "a very detailed prompt"
    assert rows(sections, "File")["Name"] == "art.png"
    assert rows(sections, "File")["Type"] == "image/png"


# ---- video -------------------------------------------------------------------------------------------

PROBE = json.loads("""{
 "streams": [
  {"codec_type": "video", "codec_name": "h264", "codec_long_name": "H.264 / AVC", "width": 1920,
   "height": 1080, "avg_frame_rate": "30000/1001", "bit_rate": "4500000", "disposition": {"attached_pic": 0}},
  {"codec_type": "audio", "codec_name": "aac", "channels": 2, "channel_layout": "stereo", "sample_rate": "48000"},
  {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000"},
  {"codec_type": "subtitle", "codec_name": "subrip"}],
 "format": {"format_long_name": "Matroska / WebM", "duration": "3725.4", "bit_rate": "4800000",
            "tags": {"TITLE": "Holiday", "creation_time": "2023-08-01T10:20:30.000000Z"}}}""")


def test_video_sections_from_ffprobe_json():
    sections = metadata.video_sections_from_probe(PROBE)
    video = rows(sections, "Video")
    assert video["Duration"] == "1:02:05"
    assert video["Resolution"] == "1920 × 1080"
    assert video["Frame rate"] == "29.97 fps"
    assert video["Bit rate"] == "4.5 Mb/s"
    audio = rows(sections, "Audio")
    assert audio["Channels"] == "stereo" and audio["Sample rate"] == "48 kHz" and audio["Tracks"] == "2"
    container = rows(sections, "Container")
    assert container["Title"] == "Holiday" and container["Created"] == "2023-08-01 10:20:30"
    assert container["Subtitle tracks"] == "1"
    assert metadata.video_sections_from_probe({}) == []


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
def test_a_real_video_is_probed(tmp_path):
    video = tmp_path / "clip.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x48:rate=10",
                    "-c:v", "mpeg4", str(video)], check=True)
    sections = metadata.read_metadata(str(video), "video")
    assert rows(sections, "Video")["Resolution"] == "64 × 48"
    assert rows(sections, "Video")["Duration"] == "0:02"


# ---- comics and books -----------------------------------------------------------------------------------

COMIC_INFO = """<?xml version="1.0"?>
<ComicInfo><Title>The Beginning</Title><Series>Smoking Behind the Supermarket</Series><Number>3</Number>
<Count>40</Count><Volume>1</Volume><Writer>Someone</Writer><Year>2021</Year><Month>4</Month><Day>9</Day>
<LanguageISO>en</LanguageISO><Manga>YesAndRightToLeft</Manga><Summary>  Two   people
meet. </Summary></ComicInfo>"""


def test_cbz_pages_and_comicinfo(tmp_path):
    cbz = tmp_path / "ch3.cbz"
    with zipfile.ZipFile(cbz, "w") as z:
        z.writestr("001.jpg", b"x")
        z.writestr("002.png", b"x")
        z.writestr("__MACOSX/003.jpg", b"x")
        z.writestr("ComicInfo.xml", COMIC_INFO)
    sections = metadata.read_metadata(str(cbz), "comic")
    assert rows(sections, "Comic")["Pages"] == "2"
    details = rows(sections, "Details")
    assert details["Series"] == "Smoking Behind the Supermarket"
    assert details["Number"] == "3 of 40"
    assert details["Published"] == "2021-04-09"
    assert details["Summary"] == "Two people meet."
    assert details["Manga"] == "YesAndRightToLeft"


def test_cbz_without_comicinfo_and_non_zip_comics(tmp_path, monkeypatch):
    plain = tmp_path / "plain.cbz"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("1.jpg", b"x")
    sections = metadata.read_metadata(str(plain), "comic")
    assert [s["title"] for s in sections] == ["File", "Comic"]
    from tetia.models import archive
    monkeypatch.setattr(archive, "find_tools", lambda kind: [])
    rar = tmp_path / "old.cbr"
    rar.write_bytes(b"Rar!\x1a\x07\x00 not a zip")
    assert "RAR comics need bsdtar" in rows(metadata.read_metadata(str(rar), "comic"), "Comic")["Archive"]
    broken = tmp_path / "broken.cbz"
    broken.write_bytes(b"PK\x03\x04 truncated")
    metadata.read_metadata(str(broken), "comic")           # must not raise


CONTAINER = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>' \
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
OPF = """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Frankenstein</dc:title><dc:creator>Mary Shelley</dc:creator><dc:language>en</dc:language>
<dc:publisher>Standard Ebooks</dc:publisher><dc:date>1818-01-01T00:00:00Z</dc:date>
<dc:identifier>url:https://standardebooks.org/ebooks/mary-shelley/frankenstein</dc:identifier>
<dc:subject>Horror</dc:subject><dc:subject>Gothic</dc:subject>
<dc:description>&lt;p&gt;A &lt;i&gt;monster&lt;/i&gt; story.&lt;/p&gt;</dc:description>
<meta name="calibre:series" content="Classics"/><meta name="calibre:series_index" content="2"/>
</metadata></package>"""


def test_epub_metadata(tmp_path):
    epub = tmp_path / "book.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
    book = rows(metadata.read_metadata(str(epub), "ebook"), "Book")
    assert book["Title"] == "Frankenstein" and book["Author"] == "Mary Shelley"
    assert book["Series"] == "Classics #2"
    assert book["Published"] == "1818-01-01"
    assert book["Subjects"] == "Horror, Gothic"
    assert book["Description"] == "A monster story."
    assert book["Format"] == "EPUB 3.0"
    broken = tmp_path / "broken.epub"
    broken.write_bytes(b"not a zip")
    assert "could not be read" in rows(metadata.read_metadata(str(broken), "ebook"), "Book")["Details"]


def test_pdf_metadata(tmp_path):
    from PySide6.QtGui import QPdfWriter, QPageSize
    from PySide6.QtCore import QSizeF
    path = tmp_path / "paper.pdf"
    writer = QPdfWriter(str(path))
    writer.setTitle("My Paper")
    writer.setCreator("Tetia tests")
    writer.setPageSize(QPageSize(QPageSize.A4))
    from PySide6.QtGui import QPainter
    painter = QPainter(writer)
    painter.drawRect(100, 100, 200, 100)
    writer.newPage()
    painter.drawRect(100, 100, 300, 100)
    painter.end()
    doc = rows(metadata.read_metadata(str(path), "ebook"), "Document")
    assert doc["Title"] == "My Paper"
    assert doc["Pages"] == "2"
    assert doc["Page size"] == "210 × 297 mm"
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4 nothing")
    assert "could not be read" in rows(metadata.read_metadata(str(junk), "ebook"), "Document")["Details"]


def test_other_book_formats_and_missing_files(tmp_path):
    mobi = tmp_path / "old.mobi"
    mobi.write_bytes(b"x")
    assert ".mobi" in rows(metadata.read_metadata(str(mobi), "ebook"), "Book")["Details"]
    gone = metadata.read_metadata(str(tmp_path / "gone.png"), "image")
    assert [s["title"] for s in gone] == ["File"] and rows(gone, "File")["Status"] == "The file is missing"


# ---- the model --------------------------------------------------------------------------------------------

def test_the_model_loads_off_the_ui_thread_and_ignores_stale_requests(tmp_path, qapp):
    from tetia.models.metadataModel import MetadataModel
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor("blue"))
    first, second = tmp_path / "one.png", tmp_path / "two.png"
    image.save(str(first))
    image.save(str(second))
    db = get_database()
    ids = []
    for path in (first, second):
        info = path.stat()
        ids.append(db.upsert_media(str(path), path.name, "image", info.st_size, int(info.st_mtime), "h" + path.name)[0])

    model = MetadataModel()
    timer = QElapsedTimer()
    timer.start()

    def wait_done():
        while model.loading and timer.elapsed() < 10_000:
            QCoreApplication.processEvents()
            QCoreApplication.sendPostedEvents()

    model.load(ids[0])
    assert model.loading
    model.load(ids[1])                       # the user moved on before the first finished
    wait_done()
    assert not model.loading
    assert rows(model.sections, "File")["Name"] == "two.png"
    model.load(-1)
    assert model.sections == [] and not model.loading
