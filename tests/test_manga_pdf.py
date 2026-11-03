"""PDFs show in the Manga tab (as well as Books); everything else is unchanged."""
from PySide6.QtCore import Qt

from tetia.models.mediaModel import MediaModel
from tetia.models.subfolderModel import SubfolderModel

MODE = MediaModel.FilterMode


def names(model):
    return [model.data(model.index(i), MediaModel.Roles.FileNameRole) for i in range(model.rowCount())]


def test_manga_tab_lists_pdfs_and_comics_in_natural_order(qapp, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    for name in ("Vol 2.pdf", "Vol 10.cbz", "Vol 1.cbz", "novel.epub", "pic.png", "clip.mp4"):
        (lib / name).write_bytes(b"x")
    model = MediaModel()
    model.load_from_qurl(str(lib))

    model.filterMode = MODE.MangaOnly
    assert names(model) == ["Vol 1.cbz", "Vol 2.pdf", "Vol 10.cbz"]       # PDF included, 2 before 10
    model.filterMode = MODE.BooksOnly
    assert names(model) == ["novel.epub", "Vol 2.pdf"]                    # a PDF is still a book too
    model.filterMode = MODE.ImagesOnly
    assert names(model) == ["pic.png"]
    model.filterMode = MODE.VideosOnly
    assert names(model) == ["clip.mp4"]
    model.filterMode = MODE.All
    assert sorted(names(model)) == sorted(["Vol 2.pdf", "Vol 10.cbz", "Vol 1.cbz", "novel.epub", "pic.png", "clip.mp4"])
    assert len(names(model)) == 6                                         # the PDF is not listed twice


def test_pdf_stays_an_ebook_kind(qapp, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "a.pdf").write_bytes(b"x")
    model = MediaModel()
    model.load_from_qurl(str(lib))
    model.filterMode = MODE.MangaOnly
    assert model.data(model.index(0), MediaModel.Roles.IsBookRole) is True
    assert model.data(model.index(0), MediaModel.Roles.IsComicRole) is False
    # so `type:ebook` still finds it and Favorites still groups it under Books
    row = model._db.conn.execute("SELECT kind FROM media WHERE name = 'a.pdf'").fetchone()
    assert row["kind"] == "ebook"


def test_subfolders_with_pdfs_appear_under_manga_and_books_only(qapp, tmp_path):
    lib = tmp_path / "lib"
    (lib / "PdfManga").mkdir(parents=True)
    (lib / "Pics").mkdir()
    (lib / "Comics").mkdir()
    (lib / "PdfManga" / "a.pdf").write_bytes(b"x")
    (lib / "Pics" / "b.png").write_bytes(b"x")
    (lib / "Comics" / "c.cbz").write_bytes(b"x")
    subs = SubfolderModel()
    subs.load(str(lib))

    def shown(mode):
        subs.filterMode = int(mode)
        return sorted(subs.data(subs.index(i), Qt.UserRole + 2) for i in range(subs.rowCount()))

    assert shown(MODE.MangaOnly) == ["Comics", "PdfManga"]
    assert shown(MODE.BooksOnly) == ["PdfManga"]
    assert shown(MODE.ImagesOnly) == ["Pics"]
    assert shown(MODE.VideosOnly) == []
