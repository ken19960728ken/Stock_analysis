# Test Suite Quick Start Guide

## Running Tests

### All Tests
```bash
uv run pytest tests/ -v
```

### By Scanner Module
```bash
# Chip Scanner tests (15 tests)
uv run pytest tests/test_chip_scanner.py -v

# Valuation Scanner tests (19 tests)
uv run pytest tests/test_valuation_scanner.py -v

# Price Scanner tests (22 tests)
uv run pytest tests/test_price_scanner.py -v

# Fundamental Scanner tests (27 tests)
uv run pytest tests/test_fundamental_scanner.py -v
```

### By Test Category
```bash
# Initialization tests only
uv run pytest tests/ -k "Initialization" -v

# Data fetching tests only
uv run pytest tests/ -k "FetchOne" -v

# Rate limiting tests only
uv run pytest tests/ -k "RateLimiting" -v

# Integration tests only
uv run pytest tests/ -k "Integration" -v
```

### Single Test
```bash
uv run pytest tests/test_chip_scanner.py::TestChipScannerFetchOne::test_fetch_one_with_string_stock_id -v
```

### With Coverage Report
```bash
# Terminal report
uv run pytest tests/ --cov=scanners --cov=core --cov-report=term-missing

# HTML report
uv run pytest tests/ --cov=scanners --cov=core --cov-report=html
# Open htmlcov/index.html in browser
```

## Test Status

**Total: 83 tests | Passed: 83 | Failed: 0 | Skipped: 0**

### Breakdown by Scanner
- ChipScanner: 15 tests
- ValuationScanner: 19 tests
- PriceScanner: 22 tests
- FundamentalScanner: 27 tests

## Key Test Files

| File | Purpose | Tests |
|------|---------|-------|
| `tests/conftest.py` | Shared fixtures and mocks | - |
| `tests/test_chip_scanner.py` | ChipScanner tests | 15 |
| `tests/test_valuation_scanner.py` | ValuationScanner tests | 19 |
| `tests/test_price_scanner.py` | PriceScanner tests | 22 |
| `tests/test_fundamental_scanner.py` | FundamentalScanner tests | 27 |

## Test Categories

Each test module covers:

1. **Initialization Tests**: Verify proper instantiation and configuration
2. **Data Fetching Tests**: Test API calls, error handling, partial success
3. **Data Transformation Tests**: Test column mapping, date conversion, schema validation
4. **Rate Limiting Tests**: Verify rate limiter behavior and API throttling
5. **Integration Tests**: Test scanner attributes and inheritance

## Debugging Failed Tests

```bash
# Verbose output with full tracebacks
uv run pytest tests/ -vv --tb=long

# Show print statements during tests
uv run pytest tests/ -s -v

# Stop on first failure
uv run pytest tests/ -x

# Show which fixtures are used
uv run pytest tests/ --fixtures | grep "test_"
```

## Test Data

All tests use realistic TSMC (2330) data:
- **Stock Code**: 2330 (Taiwan Semiconductor Manufacturing Company)
- **Price Range**: 580-595 TWD
- **Volume**: ~30 million shares
- **EPS**: 8.0-10.0 TWD
- **Dividends**: 6.0-11.0 TWD annually

## Fixtures Available

Key fixtures in `conftest.py`:
- `sample_stock_id`: "2330"
- `sample_stock_dict`: Full stock metadata
- `sample_price_data`: OHLCV data
- `sample_chip_institutional_data`: Institutional investors data
- `mock_finmind_client`: FinMind API mock
- `mock_yfinance`: Yahoo Finance mock
- `mock_rate_limiter`: Rate limiter mock
- `mock_db_save`: Database save mock

## Common Commands

```bash
# Run tests and show summary
uv run pytest tests/ --tb=no -q

# Run tests with timing info
uv run pytest tests/ --durations=10

# Run only tests matching pattern
uv run pytest tests/ -k "valuation" -v

# Run tests excluding pattern
uv run pytest tests/ -k "not Integration" -v

# Parallel execution (requires pytest-xdist)
uv run pytest tests/ -n auto
```

## Adding New Tests

1. Create test class inheriting from appropriate test class
2. Use fixtures from `conftest.py`
3. Follow naming convention: `test_<what_is_being_tested>`
4. Add docstring explaining test purpose

Example:
```python
def test_fetch_one_with_valid_stock_id(
    self,
    mock_finmind_client,
    mock_db_save,
    sample_stock_id,
    sample_chip_institutional_data,
):
    """Test that fetch_one succeeds with valid stock ID"""
    scanner = ChipScanner()
    scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
        sample_chip_institutional_data
    )
    # ... rest of test
```

## Environment Setup

Tests run with mocked external dependencies, so no `.env` file is required. However, if you have one:

```bash
# Use existing .env (optional for tests)
export SUPABASE_URL="postgresql://..."
export FINMIND_TOKEN="..."
uv run pytest tests/
```

## Notes

- Tests are fully isolated with function-scoped fixtures
- No real database writes occur
- No external API calls are made
- Tests complete in ~5-6 seconds
- All 83 tests pass consistently
