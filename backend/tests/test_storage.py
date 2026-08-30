"""Storage integrity.

The store is the only thing that outlives a process, so a silent wrong answer
here is one that persists.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from arbengine.storage import ArbStore


@pytest.fixture
def store():
    d = tempfile.mkdtemp()
    s = ArbStore(os.path.join(d, "t.db"))
    yield s
    s.close()


class TestPruneCounts:
    def test_prune_reports_rows_it_actually_removed(self, store):
        """`_exec` returned `lastrowid`, which is only meaningful after INSERT.

        After a DELETE it still holds whatever the last insert set it to, so
        seven fresh price rows and a cutoff matching none of them reported
        seven deletions.
        """
        store.record_prices([("kalshi", "m", "Yes", 0.5)] * 7)
        assert store.prune(30) == 0

    def test_prune_removes_and_counts_old_rows(self, store):
        store.record_prices([("kalshi", "m", "Yes", 0.5)] * 7)
        # A negative window puts the cutoff in the future, so everything is old.
        assert store.prune(-1) == 7
        assert store.price_history("kalshi", "m") == []

    def test_pruning_twice_reports_nothing_the_second_time(self, store):
        store.record_prices([("kalshi", "m", "Yes", 0.5)] * 3)
        assert store.prune(-1) == 3
        assert store.prune(-1) == 0


class TestForeignKeys:
    def test_foreign_keys_are_enforced(self, store):
        """The REFERENCES clauses were decorative without the pragma."""
        row = store._rows("PRAGMA foreign_keys")
        assert row and list(row[0].values())[0] == 1

    def test_a_placement_cannot_point_at_a_missing_arb(self, store):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            store.record_placement(
                999_999, "kalshi", "m", "Yes", "YES", 0.5, 10.0, "placed"
            )

    def test_prune_does_not_leave_orphan_placements(self, store):
        from tests.test_placements import _sample_arb

        arb = _sample_arb()
        row_id = store.upsert_arb(arb)
        store.record_placement(row_id, "kalshi", "m", "Yes", "YES", 0.5, 10.0, "placed")
        assert len(store.placements_for(row_id)) == 1

        # Unplaced arbs past the window are dropped; their placements go too.
        store.prune(-1)
        assert store.placements_for(row_id) == []
        assert store.arb_by_id(row_id) is None


class TestUpsertIsAtomicAndFresh:
    def test_concurrent_upserts_of_one_arb_make_one_row(self, store):
        """The read and the write used to take the lock separately.

        The store is driven from asyncio.to_thread, so two workers could both
        see "no existing row" and both insert.
        """
        import concurrent.futures as cf

        from tests.test_placements import _sample_arb

        arb = _sample_arb()
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: store.upsert_arb(arb), range(32)))

        assert len(set(ids)) == 1, f"expected one row, got {sorted(set(ids))}"
        rows = store._rows("SELECT COUNT(*) n FROM arbs")
        assert rows[0]["n"] == 1

    def test_an_update_refreshes_the_legs_not_just_last_seen(self, store):
        """A placement must never attach to legs from the first sighting."""
        from tests.test_placements import _sample_arb

        arb = _sample_arb()
        row_id = store.upsert_arb(arb)

        # Same dedupe key (venue/market/outcome/effective_price unchanged),
        # but the sizing has moved.
        bigger = arb.model_copy(
            update={
                "legs": tuple(l.model_copy(update={"stake": 500.0}) for l in arb.legs),
                "total_stake": 1000.0,
                "worst_case_profit": 31.0,
            }
        )
        assert bigger.dedupe_key() == arb.dedupe_key()
        assert store.upsert_arb(bigger) == row_id

        import json as _json

        row = store.arb_by_id(row_id)
        assert row["total_stake"] == 1000.0
        assert row["worst_case_profit"] == 31.0
        assert all(l["stake"] == 500.0 for l in _json.loads(row["legs_json"]))
