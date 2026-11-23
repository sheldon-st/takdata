import io
import zipfile


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.xml", "<MissionPackageManifest/>")
    return buf.getvalue()


def test_enablement_types_lists_all_plugins(client):
    types = {t["type_id"] for t in client.get("/api/v1/enablement-types").json()}
    assert {"adsb", "ais", "synthetic"} <= types


def test_enablement_crud(client):
    created = client.post("/api/v1/enablements", json={"type_id": "adsb", "name": "Mil"})
    assert created.status_code == 201
    eid = created.json()["id"]
    assert created.json()["running"] is False

    updated = client.put(f"/api/v1/enablements/{eid}", json={"cot_stale": 120})
    assert updated.json()["cot_stale"] == 120

    assert client.delete(f"/api/v1/enablements/{eid}").status_code == 204
    assert client.get(f"/api/v1/enablements/{eid}").status_code == 404


def test_unknown_enablement_type_is_400(client):
    resp = client.post("/api/v1/enablements", json={"type_id": "nope", "name": "x"})
    assert resp.status_code == 400


def test_start_without_tak_connection_is_409(client):
    eid = client.post("/api/v1/enablements", json={"type_id": "adsb", "name": "x"}).json()["id"]
    assert client.post(f"/api/v1/enablements/{eid}/start").status_code == 409


def test_source_api_key_is_write_only(client):
    eid = client.post("/api/v1/enablements", json={"type_id": "ais", "name": "AIS"}).json()["id"]
    source = client.post(
        f"/api/v1/enablements/{eid}/sources",
        json={
            "name": "aisstream",
            "base_url": "wss://stream.aisstream.io/v0/stream",
            "api_key": "k",
        },
    ).json()

    assert "api_key" not in source
    assert source["has_api_key"] is True
    listed = client.get(f"/api/v1/enablements/{eid}").json()["sources"][0]
    assert "api_key" not in listed and listed["has_api_key"] is True

    cleared = client.put(f"/api/v1/enablements/{eid}/sources/{source['id']}", json={"api_key": ""})
    assert cleared.json()["has_api_key"] is False


def test_known_sources_for_ais_flag_api_key(client):
    eid = client.post("/api/v1/enablements", json={"type_id": "ais", "name": "AIS"}).json()["id"]
    known = client.get(f"/api/v1/enablements/{eid}/known-sources").json()
    assert known and all(k["requires_api_key"] for k in known)


def test_status_snapshot_shape(client):
    status = client.get("/api/v1/status").json()
    assert status["tak_connected"] is False
    assert "connect_error" in status
    assert status["server_time"].endswith("+00:00")


def test_package_lifecycle(client):
    up = client.post("/api/v1/packages", files={"file": ("Ops Pack.zip", _zip_bytes())})
    assert up.status_code == 201
    pid = up.json()["package_id"]

    assert [p["package_id"] for p in client.get("/api/v1/packages").json()] == [pid]
    download = client.get(f"/api/v1/packages/{pid}")
    assert download.status_code == 200
    assert 'filename="Ops_Pack.zip"' in download.headers["content-disposition"]

    assert client.delete(f"/api/v1/packages/{pid}").status_code == 204
    assert client.get(f"/api/v1/packages/{pid}").status_code == 404


def test_package_upload_rejects_non_zip(client):
    assert client.post("/api/v1/packages", files={"file": ("x.zip", b"nope")}).status_code == 400
    assert client.post("/api/v1/packages", files={"file": ("x.txt", b"nope")}).status_code == 400
    assert client.post("/api/v1/packages", files={"file": ("x.zip", b"")}).status_code == 400


def test_wildcard_package_id_never_matches(client):
    client.post("/api/v1/packages", files={"file": ("a.zip", _zip_bytes())})
    assert client.delete("/api/v1/packages/*").status_code == 404
    assert len(client.get("/api/v1/packages").json()) == 1


def test_cert_lifecycle(client):
    up = client.post("/api/v1/tak/certs", files={"file": ("client.p12", b"\x30\x82")})
    assert up.status_code == 201
    cid = up.json()["cert_id"]
    assert client.get("/api/v1/tak/certs").json() == [{"cert_id": cid, "filename": "client.p12"}]
    assert client.delete(f"/api/v1/tak/certs/{cid}").status_code == 204


def test_tak_config_never_returns_password(client):
    resp = client.put(
        "/api/v1/tak/config", json={"cot_url": "tls://tak:8089", "cert_password": "s"}
    )
    assert resp.status_code == 200
    assert "cert_password" not in resp.json()
    assert client.get("/api/v1/tak/config").json()["cot_url"] == "tls://tak:8089"


def test_healthz_needs_no_auth(authed_client):
    resp = authed_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
