"""
Database Migration System for Komet TV

This module runs on every startup and ensures the database schema matches
the current code. It works by:

1. Reading the current DB schema (tables, columns, types)
2. Comparing against the expected schema defined in models
3. Applying changes:
   - New tables: created automatically
   - New columns: added via ALTER TABLE
   - Removed columns: ignored (SQLite doesn't support DROP COLUMN easily)
   - Type changes: ignored (SQLite doesn't support ALTER COLUMN)
   - Removed tables: optionally dropped

The migration version is tracked in a `_migrations` table.
"""

import os
import json
import hashlib
import shutil
import sqlite3
from datetime import datetime

from backend.config import settings
from backend.models.models import Base


# Schema version is derived from a hash of all model definitions
def get_schema_fingerprint() -> str:
    """Generate a hash of the current SQLAlchemy model schema."""
    schema_parts = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        columns = []
        for col in table.columns:
            columns.append(f"{col.name}:{col.type}:nullable={col.nullable}")
        schema_parts.append(f"{table_name}=[{','.join(columns)}]")
    schema_str = "|".join(schema_parts)
    return hashlib.md5(schema_str.encode()).hexdigest()[:12]


def get_current_db_schema(db_path: str) -> dict:
    """Read the current database schema."""
    if not os.path.exists(db_path):
        return {"tables": {}}

    conn = sqlite3.connect(db_path)
    tables = {}

    # Get all tables
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    table_names = [row[0] for row in cursor.fetchall()]

    for table_name in table_names:
        cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
        columns = {}
        for row in cursor.fetchall():
            # row: (cid, name, type, notnull, default, pk)
            columns[row[1]] = {
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "pk": bool(row[5]),
            }
        tables[table_name] = columns

    conn.close()
    return {"tables": tables}


def get_expected_schema() -> dict:
    """Get the expected schema from SQLAlchemy models."""
    tables = {}
    for table_name, table in Base.metadata.tables.items():
        columns = {}
        for col in table.columns:
            col_type = str(col.type).upper()
            columns[col.name] = {
                "type": col_type,
                "nullable": col.nullable,
                "primary_key": col.primary_key,
            }
        tables[table_name] = columns
    return {"tables": tables}


def run_migration_sync(db_path: str):
    """
    Run database migration synchronously.
    
    Strategy:
    1. If DB doesn't exist: create_all handles it (nothing to migrate)
    2. If DB exists: compare schemas and apply changes
       - New tables: handled by create_all
       - New columns: ALTER TABLE ADD COLUMN
       - If migration is too complex: backup old DB, create fresh, copy data
    """
    if not os.path.exists(db_path):
        print("[Migration] No existing database. Will create fresh.")
        return

    current_schema = get_current_db_schema(db_path)
    expected_schema = get_expected_schema()

    changes = detect_changes(current_schema, expected_schema)

    if not changes:
        print("[Migration] Schema is up to date.")
        return

    print(f"[Migration] Detected {len(changes)} change(s):")
    for change in changes:
        print(f"  - {change['description']}")

    # Try simple migrations first (add columns, add tables)
    simple_changes = [c for c in changes if c["type"] in ("add_column", "add_table")]
    complex_changes = [c for c in changes if c["type"] not in ("add_column", "add_table")]

    if complex_changes:
        # Complex changes require rebuild
        print("[Migration] Complex changes detected. Rebuilding database with data preservation...")
        rebuild_database(db_path, current_schema, expected_schema)
    elif simple_changes:
        # Apply simple ALTER TABLE changes
        apply_simple_migrations(db_path, simple_changes)


def detect_changes(current: dict, expected: dict) -> list:
    """Detect differences between current and expected schema."""
    changes = []
    current_tables = current["tables"]
    expected_tables = expected["tables"]

    # New tables
    for table_name in expected_tables:
        if table_name == "_migrations":
            continue
        if table_name not in current_tables:
            changes.append({
                "type": "add_table",
                "table": table_name,
                "description": f"Add new table: {table_name}",
            })
        else:
            # Check for new columns
            for col_name, col_info in expected_tables[table_name].items():
                if col_name not in current_tables[table_name]:
                    changes.append({
                        "type": "add_column",
                        "table": table_name,
                        "column": col_name,
                        "info": col_info,
                        "description": f"Add column: {table_name}.{col_name} ({col_info['type']})",
                    })

    # Removed tables (informational, we don't auto-drop)
    for table_name in current_tables:
        if table_name == "_migrations":
            continue
        if table_name not in expected_tables:
            changes.append({
                "type": "remove_table",
                "table": table_name,
                "description": f"Unused table: {table_name} (will be kept)",
            })

    return changes


def apply_simple_migrations(db_path: str, changes: list):
    """Apply simple column additions via ALTER TABLE."""
    conn = sqlite3.connect(db_path)

    for change in changes:
        if change["type"] == "add_column":
            table = change["table"]
            column = change["column"]
            info = change["info"]

            # Map SQLAlchemy types to SQLite types
            col_type = _map_type(info["type"])
            nullable = "NULL" if info.get("nullable", True) else "NOT NULL"

            try:
                sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                conn.execute(sql)
                print(f"[Migration] Applied: {change['description']}")
            except Exception as e:
                print(f"[Migration] Skipped: {change['description']} ({e})")

    conn.commit()
    conn.close()
    print("[Migration] Simple migrations complete.")


def rebuild_database(db_path: str, current_schema: dict, expected_schema: dict):
    """
    Rebuild the database preserving data.
    
    1. Backup old database
    2. Create new database with correct schema
    3. Copy data from old tables that still exist
    4. Remove backup after success
    """
    backup_path = db_path + f".backup.{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Step 1: Backup
    shutil.copy2(db_path, backup_path)
    print(f"[Migration] Backup created: {backup_path}")

    # Step 2: Create new DB
    new_path = db_path + ".new"
    if os.path.exists(new_path):
        os.remove(new_path)

    new_conn = sqlite3.connect(new_path)
    old_conn = sqlite3.connect(db_path)

    # Create tables from SQLAlchemy metadata
    from sqlalchemy import create_engine
    temp_engine = create_engine(f"sqlite:///{new_path}")
    Base.metadata.create_all(temp_engine)
    temp_engine.dispose()

    # Step 3: Copy data
    expected_tables = expected_schema["tables"]
    current_tables = current_schema["tables"]

    for table_name in expected_tables:
        if table_name not in current_tables:
            continue  # New table, no data to copy

        # Find common columns
        expected_cols = set(expected_tables[table_name].keys())
        current_cols = set(current_tables[table_name].keys())
        common_cols = expected_cols & current_cols

        if not common_cols:
            continue

        cols_str = ", ".join(common_cols)

        try:
            # Read from old
            rows = old_conn.execute(f"SELECT {cols_str} FROM {table_name}").fetchall()
            if rows:
                placeholders = ", ".join(["?"] * len(common_cols))
                new_conn.executemany(
                    f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})",
                    rows
                )
                print(f"[Migration] Copied {len(rows)} rows from {table_name}")
        except Exception as e:
            print(f"[Migration] Warning: Failed to copy {table_name}: {e}")

    new_conn.commit()
    new_conn.close()
    old_conn.close()

    # Step 4: Replace old with new
    os.remove(db_path)
    os.rename(new_path, db_path)
    print(f"[Migration] Database rebuilt successfully. Backup at: {backup_path}")


def _map_type(sqlalchemy_type: str) -> str:
    """Map SQLAlchemy type string to SQLite type."""
    t = sqlalchemy_type.upper()
    if "INTEGER" in t or "INT" in t:
        return "INTEGER"
    elif "VARCHAR" in t or "STRING" in t or "TEXT" in t:
        return "TEXT"
    elif "BOOLEAN" in t or "BOOL" in t:
        return "BOOLEAN"
    elif "DATETIME" in t or "DATE" in t:
        return "DATETIME"
    elif "FLOAT" in t or "REAL" in t or "NUMERIC" in t:
        return "REAL"
    return "TEXT"
