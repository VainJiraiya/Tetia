# Run:  python test_phase3_query.py   (stdlib only; needs no Qt and no real database)
import os, sys, sqlite3, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "models"))
import tag_query as q


class FakeResolver:
    def __init__(self, tags):
        self.tags = tags            # {(name, category): ids}

    def tag_ids(self, name, category):
        out = set()
        for (n, c), ids in self.tags.items():
            if n == name and (category is None or c == category):
                out |= set(ids)
        return out

    def wildcard_ids(self, pattern, category):
        import fnmatch
        out = set()
        for (n, c), ids in self.tags.items():
            if fnmatch.fnmatch(n, pattern) and (category is None or c == category):
                out |= set(ids)
        return out


def make_db():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE media (id INTEGER PRIMARY KEY, path TEXT, name TEXT, kind TEXT,
                            favorite INTEGER DEFAULT 0, rating INTEGER, missing INTEGER DEFAULT 0);
        CREATE TABLE media_tag (media_id INTEGER, tag_id INTEGER);
        INSERT INTO media VALUES (1,'/lib/a/Overlord 01.mkv','Overlord 01.mkv','video',1,2,0);
        INSERT INTO media VALUES (2,'/lib/a/Overlord 02.mkv','Overlord 02.mkv','video',0,NULL,0);
        INSERT INTO media VALUES (3,'/lib/b/100%_done.png','100%_done.png','image',0,3,0);
        INSERT INTO media VALUES (4,'/lib/b/Fantasy book.epub','Fantasy book.epub','ebook',0,0,0);
        INSERT INTO media VALUES (5,'/other/x.png','x.png','image',0,NULL,0);
        INSERT INTO media VALUES (6,'/lib/a/gone.png','gone.png','image',0,NULL,1);
        INSERT INTO media_tag VALUES (1,10),(2,10),(1,11),(3,12),(4,13),(4,10);
    """)
    return db


TAGS = {("isekai", "genre"): [10], ("harem", "content"): [11],
        ("fantasy", "genre"): [13], ("fantastic", "genre"): [14],
        ("overlord", "series"): [12], ("sylphie", "character"): [12]}
RANGES = [q.scope_range("/lib")]


def run(text, ranges=RANGES, tags=TAGS):
    sql, params = q.build_sql(q.parse(text), FakeResolver(tags), ranges)
    return sorted(r[0] for r in make_db().execute(sql, params).fetchall())


class ParseTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(q.parse(""), [])
        self.assertEqual(q.parse("   "), [])
        self.assertEqual(run(""), [1, 2, 3, 4])      # everything in scope, not missing

    def test_tokens_and_quotes(self):
        self.assertEqual(q.split_tokens('a "b c" name:"d e"'), ['a', '"b c"', 'name:"d e"'])
        terms = q.parse('"over lord"')
        self.assertEqual((terms[0].kind, terms[0].value), ("name", "over lord"))

    def test_prefixes(self):
        t = q.parse("-harem ~a creator:foo")
        self.assertTrue(t[0].negated and t[1].ored)
        self.assertEqual((t[2].kind, t[2].category), ("category", "creator"))

    def test_unknown_key_ignored(self):
        self.assertEqual(run("bogus:thing"), [1, 2, 3, 4])


class SearchTests(unittest.TestCase):
    def test_tag(self):
        self.assertEqual(run("isekai"), [1, 2, 4])

    def test_negative_tag(self):
        self.assertEqual(run("isekai -harem"), [2, 4])

    def test_negative_unknown_tag_falls_to_name(self):
        # "-zzz" is not a tag, so it excludes names containing zzz: nothing here
        self.assertEqual(run("-zzz"), [1, 2, 3, 4])

    def test_unknown_word_matches_filename(self):
        self.assertEqual(run("overlord"), [3])          # a tag here, so by tag
        self.assertEqual(run("overlord", tags={}), [1, 2])   # no such tag: by name

    def test_or_group(self):
        self.assertEqual(run("~harem ~fantasy"), [1, 4])

    def test_wildcard(self):
        self.assertEqual(run("fant*"), [4])

    def test_category(self):
        self.assertEqual(run("series:overlord"), [3])
        self.assertEqual(run("genre:overlord"), [])     # right name, wrong category

    def test_type_and_aliases(self):
        self.assertEqual(run("type:video"), [1, 2])
        self.assertEqual(run("type:photo"), [3])
        self.assertEqual(run("type:book"), [4])
        self.assertEqual(run("-type:video"), [3, 4])

    def test_favorite(self):
        self.assertEqual(run("is:favorite"), [1])

    def test_rating(self):
        self.assertEqual(run("rating:explicit"), [3])
        self.assertEqual(run("rating:>=mature"), [1, 3])   # NULL never matches
        self.assertEqual(run("rating:<suggestive"), [4])
        self.assertEqual(run("rating:unrated"), [2])
        self.assertEqual(run("-rating:explicit"), [1, 2, 4])  # NULL stays visible
        self.assertEqual(run("-rating:unrated"), [1, 3, 4])

    def test_name_and_wildcard_escaping(self):
        self.assertEqual(run("name:100%_"), [3])
        self.assertEqual(run("name:100_"), [])            # _ is literal, not "any char"
        self.assertEqual(run('"%"'), [3])
        self.assertEqual(run("name:OVERLORD", tags={}), [1, 2])   # case-insensitive

    def test_scope(self):
        self.assertEqual(run("type:image", ranges=[q.scope_range("/other")]), [5])
        self.assertEqual(run("", ranges=[q.scope_range("/lib/b")]), [3, 4])
        self.assertEqual(run("", ranges=[]), [])
        self.assertEqual(run("", ranges=[q.scope_range("/lib/a"), q.scope_range("/other")]), [1, 2, 5])

    def test_sibling_prefix_not_in_scope(self):
        # "/lib/a" must not match "/lib/ab/..."
        db = make_db()
        db.execute("INSERT INTO media VALUES (7,'/lib/ab/x.png','x.png','image',0,NULL,0)")
        sql, p = q.build_sql([], FakeResolver({}), [q.scope_range("/lib/a")])
        self.assertEqual(sorted(r[0] for r in db.execute(sql, p).fetchall()), [1, 2])

    def test_injection_is_inert(self):
        self.assertEqual(run("name:'; DROP TABLE media; --"), [])
        self.assertEqual(run("x') OR 1=1 --", tags={}), [])

    def test_many_tag_ids(self):
        tags = {(f"t{i}", "genre"): [100000 + i] for i in range(5000)}
        tags[("isekai", "genre")] = [10]
        self.assertEqual(run("t*", tags=tags), [])
        self.assertEqual(run("isekai", tags=tags), [1, 2, 4])


if __name__ == "__main__":
    unittest.main()
