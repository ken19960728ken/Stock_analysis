# Taiwan Stock Scanner Test Suite

## Overview

A comprehensive test suite for Taiwan stock market scanner modules, with full coverage of data fetching, transformation, and database operations. All tests use stock code **2330 (TSMC)** as the primary test subject.

**Status:** All 83 tests passing

## Test Files Created

### 1. `tests/conftest.py`
Shared pytest fixtures and configuration providing:
- **Sample Data Fixtures**: Realistic mock data for TSMC (2330) including:
  - OHLCV price data (Open/High/Low/Close/Volume)
  - Chip data (institutional investors, margin purchase, shareholding)
  - Valuation data (monthly revenue, P/E ratio, market value)
  - Financial statements (income statement, balance sheet, EPS)
  - Dividend history data

- **Mock Infrastructure**:
  - FinMind DataLoader mocking with all API endpoints
  - Yahoo Finance (`yfinance`) mocking for downloading OHLCV and dividends
  - SQLAlchemy engine and database function mocking
  - Custom `RateLimiter` mock avoiding actual delays
  - Stock list and environment variable mocking

### 2. `tests/test_chip_scanner.py`
Tests for `scanners/chip_scanner.py` (15 tests)

**Coverage Areas:**
- **Initialization** (3 tests): Instantiation, inheritance, dataset configuration
- **Data Fetching** (6 tests): String/dict targets, all/partial/no success, API exceptions
- **Data Transformation** (2 tests): Date conversion, empty dataframe handling
- **Rate Limiting** (2 tests): Limiter configuration, token passing
- **Integration** (2 tests): Resume table configuration, scan method inheritance

### 3. `tests/test_valuation_scanner.py`
Tests for `scanners/valuation_scanner.py` (19 tests)

**Coverage Areas:**
- **Initialization** (3 tests): Instantiation, inheritance, dataset structure
- **Data Fetching** (8 tests): String/dict targets, all/partial success, empty data, exceptions
- **Data Transformation** (4 tests): Date conversion, revenue structure, P/E/P/B metrics, market value
- **Rate Limiting** (3 tests): Configuration, wait calls, token usage
- **Integration** (3 tests): Target retrieval, scanner attributes, resume table

### 4. `tests/test_price_scanner.py`
Tests for `scanners/price_scanner.py` (22 tests)

**Coverage Areas:**
- **Initialization** (3 tests): Instantiation, inheritance, Yahoo rate limiter configuration
- **Target Management** (2 tests): Get targets returns list with required fields
- **Data Fetching** (9 tests): Success/failure cases, column handling, MultiIndex support, chunksize
- **Data Transformation** (3 tests): OHLCV structure, volume data, numeric price columns
- **Rate Limiting** (2 tests): Wait calls, Yahoo source configuration
- **Integration** (3 tests): Resume table, scanner name, 3-year period validation

### 5. `tests/test_fundamental_scanner.py`
Tests for `scanners/fundamental_scanner.py` (27 tests)

**Coverage Areas:**
- **Initialization** (4 tests): Instantiation, inheritance, focus metrics, dual rate limiters
- **Data Fetching** (4 tests): String/dict targets, financial + dividend data, no data cases
- **Financial Statements** (6 tests): Income/balance sheet fetching, metric filtering, date conversion, combining data
- **Dividends** (5 tests): Successful fetching, empty returns, column structure, stock ID inclusion, Yahoo symbol format
- **Rate Limiting** (2 tests): FinMind and Yahoo limiter behavior
- **Integration** (4 tests): Scanner attributes, metric inclusion, success conditions

## Test Execution

### Run All Tests
```bash
uv run pytest tests/ -v
```

### Run Tests by Module
```bash
uv run pytest tests/test_chip_scanner.py -v
uv run pytest tests/test_valuation_scanner.py -v
uv run pytest tests/test_price_scanner.py -v
uv run pytest tests/test_fundamental_scanner.py -v
```

### Run Specific Test Class
```bash
uv run pytest tests/test_chip_scanner.py::TestChipScannerFetchOne -v
```

### Run with Coverage
```bash
uv run pytest tests/ --cov=scanners --cov=core --cov-report=html
```

## Test Results

**Total Tests:** 83
**Passed:** 83 (100%)
**Failed:** 0
**Skipped:** 0

### Test Distribution by Scanner

| Scanner | Tests | Passing |
|---------|-------|---------|
| ChipScanner | 15 | 15 |
| ValuationScanner | 19 | 19 |
| PriceScanner | 22 | 22 |
| FundamentalScanner | 27 | 27 |
| **Total** | **83** | **83** |

## Mocking Strategy

All tests use comprehensive mocking to avoid external API calls:

1. **FinMind API**: Mocked `DataLoader` with configurable return values for each method
2. **Yahoo Finance**: Mocked `yfinance.download()` and `yfinance.Ticker()`
3. **Database**: Mocked SQLAlchemy engine, connection, and `to_sql()` operations
4. **Rate Limiting**: Custom `MockRateLimiter` with no-op delays
5. **Environment**: Patched environment variables and configuration loaders

This ensures:
- Tests run in seconds without network I/O
- No dependency on external APIs or databases
- Full deterministic test behavior
- Isolation from production systems

## Test Data Characteristics

Sample data uses **TSMC (2330)** with realistic values:

- **OHLCV**: Price ~580-595 TWD, Volume ~30M shares
- **EPS**: 8.0-10.0 TWD (quarterly)
- **Dividends**: 6.0-11.0 TWD (annual)
- **P/E Ratio**: 18.5-19.2x
- **P/B Ratio**: 2.5-2.7x
- **Revenue**: 150-165 billion TWD (monthly)
- **Market Cap**: 17-17.5 trillion TWD

## Key Test Categories

### 1. Initialization Tests
Verify scanners properly inherit from `BaseScanner` and initialize with correct attributes and configurations.

### 2. Data Fetching Tests
Cover:
- Successful data retrieval with valid inputs
- Partial data retrieval (some datasets succeed, others fail)
- Empty response handling
- API exception handling and continuation logic

### 3. Data Transformation Tests
Verify:
- Date column conversion to date objects
- DataFrame column naming and structure
- Data type conversions (numeric, datetime)
- Schema compliance for database writes

### 4. Rate Limiting Tests
Ensure:
- Rate limiter is properly instantiated with correct source
- Wait calls are invoked between API requests
- FinMind tokens are properly passed and used

### 5. Integration Tests
Test:
- Scanner attributes (name, resume_table)
- Target list retrieval
- Success/failure metrics
- Resume capability for checkpoint functionality

## Dependencies

The test suite requires:
- pytest >= 7.0.0
- pandas
- finmind >= 1.9.5
- yfinance
- sqlalchemy
- python-dotenv
- tqdm

All are available in the project's virtual environment via `uv sync`.

## Running Tests in CI/CD

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/ -v --tb=short

# With coverage report
uv run pytest tests/ --cov=scanners --cov=core --cov-report=term-missing
```

## Future Enhancements

Potential additions to the test suite:

1. **Parametrized Tests**: Test multiple stock codes (2330, 2317, 2454, 0050, etc.)
2. **Performance Tests**: Measure scanner execution time with large datasets
3. **Concurrency Tests**: Test thread-safe behavior with multiple concurrent scans
4. **Error Recovery**: Test graceful degradation on partial failures
5. **Database Transaction Tests**: Verify `APPEND` mode behavior with duplicates
6. **Integration Tests**: Optional real API testing with fixtures disabled

## Notes

- All tests are fully isolated and can run in any order
- Tests use realistic TSMC (2330) data to validate logic with real-world values
- Mocking ensures tests run without network I/O or database access
- Test execution time is minimal (full suite in ~5-6 seconds)
- No test cleanup needed as all mocks are function-scoped

## Author

Test suite created with comprehensive coverage for Taiwan stock market data pipelines using stock code 2330 (Taiwan Semiconductor Manufacturing Company) as the primary test subject.
