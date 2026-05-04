#!/bin/bash
# ratethat.tennis — Apply prediction tracking + systems schema additions
cd "$(dirname "$0")"
echo "============================================"
echo " ratethat.tennis — Predictions Schema"
echo "============================================"
echo ""

pip3 install psycopg2-binary --quiet --break-system-packages 2>/dev/null || \
pip3 install psycopg2-binary --quiet

python3 - <<'PYEOF'
import os
import psycopg2

DB = "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"

sql_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "pipeline",
    "predictions_schema.sql",
)
with open(sql_path) as f:
    sql = f.read()

# Split into statements naively but skip $$-quoted bodies (we don't have any here).
# Strip --comment lines first.
raw_stmts = sql.split(";")
statements = []
for s in raw_stmts:
    lines = [l for l in s.splitlines() if not l.strip().startswith("--")]
    stmt = "\n".join(lines).strip()
    if stmt:
        statements.append(stmt)

print("Connecting to Railway Postgres...")
conn = psycopg2.connect(DB)
conn.autocommit = True

print(f"Applying {len(statements)} statements...")
ok = errors = skipped = 0
for i, stmt in enumerate(statements, 1):
    try:
        with conn.cursor() as cur:
            cur.execute(stmt)
        ok += 1
    except psycopg2.errors.DuplicateTable:
        skipped += 1
    except psycopg2.errors.DuplicateObject:
        skipped += 1
    except psycopg2.errors.DuplicateColumn:
        skipped += 1
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg:
            skipped += 1
        else:
            print(f"  ⚠️  Statement {i}: {e}")
            print(f"      {stmt[:160]}...")
            errors += 1

conn.close()
print(f"\n✅ Done! {ok} applied, {skipped} already existed, {errors} errors.")
PYEOF

echo ""
echo "============================================"
echo " Done! Press any key to close."
echo "============================================"
read -n 1
