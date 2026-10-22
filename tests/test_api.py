import pytest
from fastapi.testclient import TestClient

from app.main import app, accounts

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_accounts():
    accounts.clear()
    yield
    accounts.clear()


def create(owner="Alice", balance=100):
    return client.post("/accounts", json={"owner": owner, "balance": balance}).json()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_account():
    r = client.post("/accounts", json={"owner": "Alice", "balance": 50})
    assert r.status_code == 201
    assert r.json()["owner"] == "Alice"
    assert r.json()["balance"] == 50


def test_create_account_invalid_balance():
    r = client.post("/accounts", json={"owner": "Alice", "balance": -5})
    assert r.status_code == 422


def test_get_account():
    acc = create()
    r = client.get(f"/accounts/{acc['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == acc["id"]


def test_get_account_not_found():
    r = client.get("/accounts/inconnu")
    assert r.status_code == 404


def test_transfer_success():
    a = create("Alice", 100)
    b = create("Bob", 20)
    r = client.post("/transfers", json={"from_id": a["id"], "to_id": b["id"], "amount": 30})
    assert r.status_code == 200
    assert r.json()["from_balance"] == 70
    assert r.json()["to_balance"] == 50


def test_transfer_insufficient_funds():
    a = create("Alice", 10)
    b = create("Bob", 0)
    r = client.post("/transfers", json={"from_id": a["id"], "to_id": b["id"], "amount": 50})
    assert r.status_code == 400
    assert r.json()["detail"] == "Solde insuffisant"


def test_transfer_unknown_account():
    a = create()
    r = client.post("/transfers", json={"from_id": a["id"], "to_id": "inconnu", "amount": 5})
    assert r.status_code == 404


def test_transfer_same_account():
    a = create()
    r = client.post("/transfers", json={"from_id": a["id"], "to_id": a["id"], "amount": 5})
    assert r.status_code == 400


def test_transfer_invalid_amount():
    a = create()
    b = create("Bob", 0)
    r = client.post("/transfers", json={"from_id": a["id"], "to_id": b["id"], "amount": 0})
    assert r.status_code == 422


def test_simulated_delay(monkeypatch):
    monkeypatch.setenv("SIMULATED_DELAY_MS", "1")
    assert client.get("/health").status_code == 200