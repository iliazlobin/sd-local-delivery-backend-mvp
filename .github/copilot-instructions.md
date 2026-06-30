# Copilot Code Review Instructions

This project is a FastAPI-based REST API for a local delivery platform.

## Architecture
- FastAPI app factory pattern with async endpoints
- PostgreSQL 16 for all data, Redis 7 for caching
- Alembic for database migrations
- pydantic-settings for configuration
- Routers -> Services -> Models layering (thin routers, business logic in services)

## Code Style
- Python 3.12+
- Ruff linting with line-length=100, double quotes
- B008 suppressed globally (FastAPI Depends()/Query() in function defaults is the standard pattern)
- Use `raise ... from e` or `raise ... from None` in except blocks (B904)

## Testing
- Unit tests in tests/unit/ (isolated, mock IO)
- Functional tests in tests/functional/ (in-process endpoint scenarios)
- Acceptance tests in verify/acceptance/ (black-box HTTP, never edit to satisfy lint)

## Review Focus
- Watch for SQL injection, missing input validation
- Check that error handling uses proper FastAPI HTTPException patterns
- Verify async/await consistency (no sync calls inside async endpoints)
- Ensure database sessions are properly managed (commit/rollback)
- Look for missing idempotency guarantees on order creation
- Confirm inventory reservation uses proper row-level locking
