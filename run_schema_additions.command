#!/bin/bash
# ratethat.tennis — Apply schema additions to Railway Postgres
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — Schema Additions"
echo "============================================"
echo ""

pip3 install psycopg2-binary --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary --quiet

python3 - <<'PYEOF'
import os, sys, re
import psycopg2

DB = "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"

sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "pipeline", "schema_additions.sql")
with open(sql_path) as f:
    sql = f.read()

# Remove comment-only lines, split on semicolons
raw_stmts = sql.split(";")
statements = []
for s in raw_stmts:
    # Strip comment lines and whitespace
    lines = [l for l in s.splitlines() if not l.strip().startswith("--")]
    stmt = "\n".join(lines).strip()
    if stmt:
        statements.append(stmt)

print(f"Connecting to Railway Postgres...")
conn = psycopg2.connect(DB)
conn.autocommit = True   # DDL statements each auto-commit

print(f"Applying {len(statements)} statements...")
ok = errors = skipped = 0
for i, stmt in enumerate(statements, 1):
    try:
        with conn.cursor() as cur:
            cur.execute(stmt)
        ok += 1
    except psycopg2.errors.DuplicateTable:
        skipped += 1   # table already exists — fine
    except psycopg2.errors.DuplicateObject:
        skipped += 1   # index already exists — fine
    except psycopg2.errors.DuplicateColumn:
        skipped += 1   # column already exists — fine
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg:
            skipped += 1
        else:
            print(f"  ⚠️  Statement {i}: {e}")
            errors += 1

conn.close()
print(f"\n✅ Done! {ok} applied, {skipped} already existed, {errors} errors.")
if errors == 0:
    print("   All schema additions in place.")
PYEOF

echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
