import pytest

from application.services.sql_tool import SqlValidationError, validate_select


# ── Accepted queries ──────────────────────────────────────────────────────────

def test_simple_count():
    validate_select("SELECT count(*) FROM events")


def test_aggregate_with_filter():
    sql = (
        "SELECT date_trunc('day', occurred_at) AS d, count(*) "
        "FROM events WHERE type='diaper' GROUP BY d ORDER BY d"
    )
    validate_select(sql)


def test_jsonb_cast():
    sql = (
        "SELECT avg((payload->>'duration_min')::int) "
        "FROM events WHERE type='sleep_end' AND occurred_at > now() - interval '7 days'"
    )
    validate_select(sql)


def test_cte_select():
    sql = """
    WITH feedings AS (
        SELECT occurred_at, (payload->>'duration_min')::int AS dur
        FROM events WHERE type = 'feed_breast'
    )
    SELECT avg(dur) FROM feedings
    """
    validate_select(sql)


def test_subquery():
    sql = (
        "SELECT * FROM (SELECT id, occurred_at FROM events LIMIT 10) AS sub"
    )
    validate_select(sql)


def test_returns_normalized_sql():
    sql = "  SELECT 1  "
    result = validate_select(sql)
    assert result.strip() == "SELECT 1"


# ── Rejected queries ──────────────────────────────────────────────────────────

def test_rejects_insert():
    with pytest.raises(SqlValidationError):
        validate_select("INSERT INTO events (type) VALUES ('note')")


def test_rejects_update():
    with pytest.raises(SqlValidationError):
        validate_select("UPDATE events SET type='note' WHERE id='1'")


def test_rejects_delete():
    with pytest.raises(SqlValidationError):
        validate_select("DELETE FROM events WHERE id='1'")


def test_rejects_drop():
    with pytest.raises(SqlValidationError):
        validate_select("DROP TABLE events")


def test_rejects_create():
    with pytest.raises(SqlValidationError):
        validate_select("CREATE TABLE evil (x int)")


def test_rejects_multi_statement():
    with pytest.raises(SqlValidationError):
        validate_select("SELECT 1; DELETE FROM events")


def test_rejects_unknown_table():
    with pytest.raises(SqlValidationError):
        validate_select("SELECT * FROM users")


def test_rejects_pg_read_file():
    with pytest.raises(SqlValidationError):
        validate_select("SELECT pg_read_file('/etc/passwd')")


def test_rejects_dml_inside_cte():
    with pytest.raises(SqlValidationError):
        validate_select(
            "WITH x AS (DELETE FROM events RETURNING 1) SELECT * FROM x"
        )


def test_rejects_empty():
    with pytest.raises(SqlValidationError):
        validate_select("")


def test_rejects_whitespace_only():
    with pytest.raises(SqlValidationError):
        validate_select("   ")
