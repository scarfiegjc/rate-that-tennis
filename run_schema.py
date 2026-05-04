#!/usr/bin/env python3
"""One-shot script to run the ratethat.tennis schema against Railway Postgres."""
import subprocess, sys, os, tempfile

print("Installing database driver...")
tmp = tempfile.mkdtemp()
subprocess.run([sys.executable, "-m", "pip", "install", "pg8000", "--target", tmp, "-q"], check=True)
sys.path.insert(0, tmp)

import pg8000.native

DB = "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"

schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
with open(schema_path) as f:
    sql = f.read()

print("Connecting to Railway Postgres...")
conn = pg8000.native.Connection(
    user="postgres",
    password="DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS",
    host="switchyard.proxy.rlwy.net",
    port=39343,
    database="railway",
    ssl_context=True
)

print("Running schema...")
# Split on semicolons and run statement by statement
statements = [s.strip() for s in sql.split(";") if s.strip()]
ok = 0
for stmt in statements:
    try:
        conn.run(stmt)
        ok += 1
    except Exception as e:
        # Skip harmless "already exists" notices
        if "already exists" in str(e) or "DuplicateObject" in str(e):
            ok += 1
        else:
            print(f"  Warning: {e}")

conn.close()
print(f"\n✅ Done! {ok} statements executed. Your ratethat.tennis database is ready.")
