import multiprocessing as mp

from decision_router import Cache, Record


def rec(k, answer="A"):
    return Record(key=k, model="m", version="v", request={"q": k}, response={"answers": {"q": answer}})


def test_first_answer_stays(cache):
    assert cache.put(rec("k", "A"))
    assert not cache.put(rec("k", "B"))
    assert cache.get("k") == {"answers": {"q": "A"}}
    assert cache.get("missing") is None


def test_labels_deduplicated_regardless_of_field_order(cache):
    cache.put(rec("k"))
    assert cache.label("k", {"a": 1, "b": 2})
    assert not cache.label("k", {"b": 2, "a": 1})
    assert not cache.label("k", None) and not cache.label("k", {})
    assert cache.counts() == (1, 1)


def test_reopen_keeps_everything(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put(rec("k"))
    c.label("k", {"t": 1})
    c.close()
    assert Cache(tmp_path / "c.sqlite").counts() == (1, 1)


def _writer(path, start, n):
    c = Cache(path)
    for i in range(start, start + n):
        c.put(rec(f"k{i}"))
        c.label(f"k{i}", {"writer": start})
    c.close()


def test_concurrent_writer_processes(tmp_path):
    path = tmp_path / "c.sqlite"
    Cache(path).close()
    ctx = mp.get_context("spawn")
    # four processes, overlapping key ranges: k0..k299 in total, each key written by up to two
    procs = [ctx.Process(target=_writer, args=(path, s, 150)) for s in (0, 50, 100, 150)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert all(p.exitcode == 0 for p in procs)
    c = Cache(path)
    assert c.counts() == (300, 600)
    assert c.con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
