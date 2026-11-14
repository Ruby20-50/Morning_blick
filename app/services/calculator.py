"""Basic arithmetic operations (moved from app/data/dataset.py)."""


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


OPERATIONS = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}


if __name__ == "__main__":
    a, b = 10, 5
    print(add(a, b))
    print(subtract(a, b))
    print(multiply(a, b))
    print(divide(a, b))
