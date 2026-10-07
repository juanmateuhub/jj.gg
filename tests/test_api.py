"""Pruebas de la aplicación web con datos sintéticos."""
import random

import pytest
from fastapi.testclient import TestClient

import api
from lolmatchups import config, db
from lolmatchups.parser import parse_match
from tests.test_pipeline import _meta, fake_game, static  # noqa: F401  (fixture)


@pytest.fixture
def client(static, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "web.db")
    conn = db.connect()
    rng = random.Random(2)
    for i in range(40):
        parsed, _ = parse_match(*fake_game(i, rng), static.legendary_item_ids(), _meta(i))
        db.save_parsed(conn, parsed)
    conn.close()
    monkeypatch.setattr(api, "_static", static)
    return TestClient(api.app)


def test_index_and_options(client):
    assert "<title>jj.gg</title>" in client.get("/").text
    o = client.get("/api/options").json()
    assert o["total_matches"] == 40 and o["patches"] == ["26.18"] and o["platforms"] == ["euw1"]
    assert o["tiers"][0] == config.MIN_TIER
    assert {s["name"] for s in o["spells"]} >= {"Prender", "Teleportar"}


def test_matchup(client):
    r = client.get("/api/matchup", params={"a": "Darius", "b": "Garen", "role": "top", "spells_a": "Prender"})
    assert r.status_code == 200
    data = r.json()
    assert data["games"] == 20 and data["names"]["Darius"] == "Darius"
    assert [L["level"] for L in data["levels"]] == [1, 3, 6, 9, 12, 15, 18]
    assert set(data["lane"]) == {"Darius", "Garen"}
    assert data["art"]["Darius"]["splash"].endswith("Darius_0.jpg")


def test_errors(client):
    assert client.get("/api/matchup", params={"a": "Nadie", "b": "Garen", "role": "top"}).status_code == 404
    assert client.get("/api/matchup", params={"a": "Darius", "b": "Garen", "role": "mid"}).status_code == 400
