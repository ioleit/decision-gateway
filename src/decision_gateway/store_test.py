import multiprocessing as mp
from datetime import UTC, datetime, timedelta
from pathlib import Path

from decision_gateway.store import Observation, RequestEvent, SQLiteStore

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def obs(i: str, k: str = "k", model: str = "m", at: datetime = T0) -> Observation:
    response = {"model": model, "provider": "P", "answers": {}, "usage": {"cost": 0.1}}
    return Observation(i, k, "http://x/v1/systemone", {"model": "m"}, response, at, 0.1)


def test_observations_are_found_by_key_oldest_first(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "s.sqlite") as store:
        store.append_observation(obs("2", at=T0 + timedelta(seconds=1)))
        store.append_observation(obs("1"))
        store.append_observation(obs("3", k="other"))
        found = store.observations("k")
        assert [o.id for o in found] == ["1", "2"]
        assert found[0] == obs("1")
        assert (found[0].served_model, found[0].provider) == ("m", "P")
        assert store.observations("missing") == []
        row = store.con.execute("SELECT model, provider, cost FROM observations WHERE id = '1'").fetchone()
        assert row == ("m", "P", 0.1)


def test_requests_are_recorded(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "s.sqlite") as store:
        event = RequestEvent("r1", T0, "jev", "k", {"run": "r1", "item": 1}, "1", hit=True, accepted=True)
        store.append_request(event)
        row = store.con.execute("SELECT model, labels, observation, hit, accepted FROM requests").fetchone()
        assert row == ("jev", '{"item":1,"run":"r1"}', "1", 1, 1)


def test_reopen_keeps_everything(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "s.sqlite") as store:
        store.append_observation(obs("1"))
    with SQLiteStore(tmp_path / "s.sqlite") as store:
        assert [o.id for o in store.observations("k")] == ["1"]


def _writer(path: Path, start: int, n: int) -> None:
    with SQLiteStore(path) as store:
        for i in range(start, start + n):
            store.append_observation(obs(f"o{i}", k=f"k{i % 10}"))


def test_concurrent_writer_processes(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite"
    SQLiteStore(path).close()
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(path, s, 100)) for s in (0, 100, 200, 300)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert all(p.exitcode == 0 for p in procs)
    with SQLiteStore(path) as store:
        assert store.con.execute("SELECT count(*) FROM observations").fetchone() == (400,)
        assert len(store.observations("k3")) == 40
        assert store.con.execute("PRAGMA journal_mode").fetchone() == ("wal",)
