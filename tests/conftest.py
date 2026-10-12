import os

# Point the app at the test database before anything imports clearfeed:
# core/db.py builds its engine from DATABASE_URL at import time.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://clearfeed:clearfeed@localhost:5432/clearfeed_test",
)
