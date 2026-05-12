import uuid

import sqlglot
import sqlglot.expressions as exp


class SqlValidationError(Exception):
    pass


_ALLOWED_TABLES = {'events'}

_DENIED_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,
)

_DENIED_FUNCTIONS = frozenset({
    'pg_read_file', 'pg_ls_dir', 'pg_read_binary_file',
    'dblink', 'dblink_exec',
    'lo_import', 'lo_export',
})

_DENIED_SCHEMAS = frozenset({'pg_catalog', 'information_schema'})


def validate_select(sql: str) -> str:
    sql = sql.strip()
    if not sql:
        raise SqlValidationError('empty query')

    try:
        statements = sqlglot.parse(sql, read='postgres', error_level=sqlglot.ErrorLevel.RAISE)
    except Exception as exc:
        raise SqlValidationError(f'parse error: {exc}') from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlValidationError('exactly one statement is required')

    stmt = statements[0]

    if not isinstance(stmt, exp.Select):
        raise SqlValidationError(
            f'only SELECT statements are allowed, got {type(stmt).__name__}'
        )

    # Collect CTE aliases so they are valid table references
    cte_names: set[str] = {
        cte.alias.lower()
        for cte in stmt.find_all(exp.CTE)
        if cte.alias
    }

    allowed_tables = _ALLOWED_TABLES | cte_names

    # Walk the full AST to check for forbidden constructs
    for node in stmt.walk():
        if isinstance(node, _DENIED_NODE_TYPES):
            raise SqlValidationError(
                f'{type(node).__name__} statements are not allowed'
            )

        if isinstance(node, exp.Table):
            table_name = (node.name or '').lower()
            db = (node.args.get('db') or node.args.get('catalog') or '')
            if isinstance(db, exp.Expression):
                db = db.name or ''
            if db.lower() in _DENIED_SCHEMAS:
                raise SqlValidationError(f'access to schema {db!r} is not allowed')
            if table_name and table_name not in allowed_tables:
                raise SqlValidationError(
                    f'table {table_name!r} is not allowed; only the events table may be queried'
                )

        if isinstance(node, exp.Anonymous):
            func_name = (node.name or '').lower()
            if func_name in _DENIED_FUNCTIONS:
                raise SqlValidationError(f'function {func_name!r} is not allowed')

    return sql


def extract_uuid_ids(result: dict) -> list[uuid.UUID]:
    cols = result.get('columns', [])
    rows = result.get('rows', [])
    id_indexes = [
        index
        for index, column in enumerate(cols)
        if str(column).lower() == 'id' or str(column).lower().endswith('_id')
    ]
    if not id_indexes:
        return []
    ids: list[uuid.UUID] = []
    for row in rows:
        for id_idx in id_indexes:
            try:
                ids.append(uuid.UUID(str(row[id_idx])))
            except (ValueError, TypeError, IndexError):
                pass
    return ids


_extract_uuid_ids = extract_uuid_ids
