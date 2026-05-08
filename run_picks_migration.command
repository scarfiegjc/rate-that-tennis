#!/bin/bash
# run_picks_migration.command
# Creates the users and user_picks tables in the Railway database.
# Double-click to run — uses Python (no psql required).

cd "$(dirname "$0")"

echo ""
echo "🎾 ratethat.tennis — My Picks migration"
echo "========================================="
echo ""

python3 - <<'PYEOF'
import os, sys

# Load .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
if not db_url:
    print("❌  DATABASE_URL not set. Add it to your .env file.")
    sys.exit(1)

try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    os.system("pip3 install psycopg2-binary --break-system-packages -q")
    import psycopg2

sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline", "picks_schema.sql")
with open(sql_path) as f:
    sql = f.read()

print("Connecting to Railway database...")
try:
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    # Run statement by statement (skip empty lines and comment-only blocks)
    import re
    statements = [s.strip() for s in sql.split(";") if s.strip() and not re.match(r'^[\s\-]+$', s)]
    for stmt in statements:
        if stmt:
            cur.execute(stmt)
    cur.close()
    conn.close()
    print("")
    print("✅  Migration complete!")
    print("   Tables created: users, user_picks")
    print("")
    print("Next steps:")
    print("  1. Set RTT_JWT_SECRET in your Railway environment variables")
    print("     (any long random string — generate one at: openssl rand -hex 32)")
    print("  2. Deploy the updated API to Railway (git push)")
    print("  3. Deploy the updated frontend to Railway (git push)")
except Exception as e:
    print(f"❌  Migration failed: {e}")
    sys.exit(1)
PYEOF

echo ""
read -p "Press Enter to close..."
