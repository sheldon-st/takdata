import pytest

from app.services.file_store import FileStore, is_valid_id, safe_stem


@pytest.mark.parametrize("value", ["0123456789abcdef", "legacy-id", "A1"])
def test_accepts_plain_ids(value):
    assert is_valid_id(value)


@pytest.mark.parametrize("value", ["", "*", "../x", "a/b", "a_b", "a.b", "x" * 65, "[ab]"])
def test_rejects_glob_and_path_ids(value):
    assert not is_valid_id(value)


def test_safe_stem_strips_unsafe_characters():
    assert safe_stem("../../etc/pass wd.zip") == "pass_wd"
    assert safe_stem("my pkg.v1.zip") == "my_pkg.v1"
    assert safe_stem("...zip") == "file"


def test_round_trip(tmp_path):
    store = FileStore(tmp_path, ".zip")
    saved = store.save("Ops Pack.zip", b"data")

    assert store.list()[0] | {"mtime": None} == {
        "id": saved["id"],
        "filename": "Ops_Pack.zip",
        "size": 4,
        "mtime": None,
    }
    path = store.path_for(saved["id"])
    assert path is not None and path.read_bytes() == b"data"
    assert store.delete(saved["id"]) is True
    assert store.list() == []


def test_wildcard_id_matches_nothing(tmp_path):
    store = FileStore(tmp_path, ".zip")
    store.save("a.zip", b"x")

    assert store.path_for("*") is None
    assert store.delete("*") is False
    assert len(store.list()) == 1


def test_legacy_file_without_original_name(tmp_path):
    (tmp_path / "abc123.p12").write_bytes(b"x")
    store = FileStore(tmp_path, ".p12")

    assert store.path_for("abc123") == tmp_path / "abc123.p12"
    assert store.list()[0]["filename"] == "abc123.p12"
