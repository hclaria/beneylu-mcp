import stat

from beneylu_mcp.state import StateStore


def test_creates_missing_dirs_with_private_perms(tmp_path):
    p = tmp_path / "a" / "b" / "state.db"
    StateStore(p)
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_kv_roundtrip_and_delete(tmp_path):
    s = StateStore(tmp_path / "s.db")
    s.set("k", "v")
    assert s.get("k") == "v"
    s.delete("k")
    assert s.get("k") is None


def test_mark_seen_upserts(tmp_path):
    s = StateStore(tmp_path / "s.db")
    s.mark_seen([("post", "A", "f1")])
    s.mark_seen([("post", "A", "f2")])
    assert s.seen_fingerprint("post", "A") == "f2"
    assert s.seen_fingerprint("notification", "A") is None


def test_persists_across_instances(tmp_path):
    StateStore(tmp_path / "s.db").set("refresh_token", "x")
    assert StateStore(tmp_path / "s.db").get("refresh_token") == "x"
