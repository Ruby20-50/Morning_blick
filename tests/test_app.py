from fastapi.testclient import TestClient

from app.main import app
from app.services import calculator

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_calculator_functions():
    assert calculator.add(10, 5) == 15
    assert calculator.subtract(10, 5) == 5
    assert calculator.multiply(10, 5) == 50
    assert calculator.divide(10, 5) == 2
    assert calculator.divide(10, 0) is None


def test_calculate_endpoint():
    response = client.post("/calculate/add", json={"a": 10, "b": 5})
    assert response.status_code == 200
    assert response.json()["result"] == 15


def test_calculate_divide_by_zero():
    response = client.post("/calculate/divide", json={"a": 10, "b": 0})
    assert response.status_code == 200
    assert response.json()["result"] is None


def test_unknown_operation():
    response = client.post("/calculate/power", json={"a": 2, "b": 3})
    assert response.status_code == 422


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Morning Blick" in response.text
