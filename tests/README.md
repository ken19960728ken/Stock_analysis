# Taiwan Stock Scanner Test Suite

This directory contains comprehensive tests for the Taiwan stock market scanner modules.

## Files

- `conftest.py` - Shared pytest fixtures and mock infrastructure
- `test_chip_scanner.py` - Tests for ChipScanner (15 tests)
- `test_valuation_scanner.py` - Tests for ValuationScanner (19 tests)
- `test_price_scanner.py` - Tests for PriceScanner (22 tests)
- `test_fundamental_scanner.py` - Tests for FundamentalScanner (27 tests)

## Quick Start

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific module
uv run pytest tests/test_chip_scanner.py -v

# Run with coverage
uv run pytest tests/ --cov=scanners --cov=core --cov-report=html
```

## Test Coverage

- **Total Tests**: 83
- **Pass Rate**: 100% (83/83)
- **Primary Stock Code**: 2330 (TSMC)

### By Scanner

| Scanner | Tests | Status |
|---------|-------|--------|
| ChipScanner | 15 | PASS |
| ValuationScanner | 19 | PASS |
| PriceScanner | 22 | PASS |
| FundamentalScanner | 27 | PASS |

## Key Features

- Comprehensive mocking of external APIs (FinMind, Yahoo Finance)
- Realistic TSMC (2330) test data
- Isolated, deterministic tests with no external dependencies
- Fast execution (~5-6 seconds for full suite)
- Clear test organization by functionality

## Documentation

- `TESTS_SUMMARY.md` - Complete test suite documentation
- `TEST_QUICKSTART.md` - Quick reference for common commands
