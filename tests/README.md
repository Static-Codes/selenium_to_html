## Running test suite:
* Note: these commands should be run from the root project directory.

```py
PYTHONPATH=. uv run --no-project --with pytest --with pytest-asyncio -m pytest tests/regression
```

```py
PYTHONPATH=. uv run --no-project --with pytest --with pytest-asyncio -m pytest tests/integration
```

```py
PYTHONPATH=. uv run --no-project --with pytest --with pytest-asyncio -m pytest conftest.py
```