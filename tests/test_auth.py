ADMIN = {"x-authentik-username": "alice", "x-authentik-groups": "tak-manager-admin"}
VIEWER = {"x-authentik-username": "bob", "x-authentik-groups": "users|tak-manager-viewer"}
OUTSIDER = {"x-authentik-username": "eve", "x-authentik-groups": "users"}


def test_missing_headers_is_401(authed_client):
    assert authed_client.get("/api/v1/status").status_code == 401


def test_me_reports_role(authed_client):
    assert authed_client.get("/api/v1/me", headers=ADMIN).json() == {
        "username": "alice",
        "role": "admin",
        "auth_enabled": True,
    }
    assert authed_client.get("/api/v1/me", headers=VIEWER).json()["role"] == "viewer"


def test_viewer_can_read_but_not_write(authed_client):
    assert authed_client.get("/api/v1/enablements", headers=VIEWER).status_code == 200
    created = authed_client.post(
        "/api/v1/enablements", json={"type_id": "adsb", "name": "x"}, headers=VIEWER
    )
    assert created.status_code == 403


def test_user_without_group_is_403(authed_client):
    assert authed_client.get("/api/v1/enablements", headers=OUTSIDER).status_code == 403


def test_auth_disabled_treats_caller_as_admin(client):
    me = client.get("/api/v1/me").json()
    assert me == {"username": "anonymous", "role": "admin", "auth_enabled": False}
