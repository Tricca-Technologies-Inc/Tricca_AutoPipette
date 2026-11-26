"""The kiosk refuses requests from other web sites.

It has no authentication: binding loopback is its only protection
(ADR-0002). That doesn't stop a web page open in a browser on the same
machine. A form can POST to a body-less route such as ``/home`` with no
CORS preflight, and DNS rebinding lets a page reach the kiosk under the
page's own host name. So the kiosk answers only to its own host names, and
refuses a state-changing request whose ``Origin`` is another site.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autopipette_kiosk import main as kiosk_main


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(kiosk_main, "_control_client", None)
    return TestClient(kiosk_main.app, base_url="http://127.0.0.1:8000")


def test_a_foreign_host_is_refused(client: TestClient) -> None:
    response = client.get("/status", headers={"host": "evil.example"})

    assert response.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "localhost"])
def test_its_own_host_names_are_served(client: TestClient, host: str) -> None:
    assert client.get("/status", headers={"host": host}).status_code == 200


def test_a_cross_site_post_is_refused(client: TestClient) -> None:
    response = client.post("/home", headers={"origin": "http://evil.example"})

    assert response.status_code == 403


def test_another_local_port_is_another_site(client: TestClient) -> None:
    response = client.post("/home", headers={"origin": "http://127.0.0.1:3000"})

    assert response.status_code == 403


def test_a_same_origin_post_gets_through(client: TestClient) -> None:
    response = client.post("/home", headers={"origin": "http://127.0.0.1:8000"})

    assert response.status_code == 503  # past the check, to the missing daemon


def test_a_post_with_no_origin_gets_through(client: TestClient) -> None:
    # curl and scripts send no Origin; only browsers do.
    assert client.post("/home").status_code == 503
