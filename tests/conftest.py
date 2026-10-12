import os

# Set every setting explicitly so a developer's .env can't change test results
# (environment variables take priority over .env). This must run before
# anything imports clearfeed: core/db.py builds its engine at import time.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://clearfeed:clearfeed@localhost:5432/clearfeed_test",
)
os.environ["ACTIVE_TICKET_LIMIT"] = "5"
os.environ["ASSIGNMENT_LOCK_TIMEOUT_SECONDS"] = "5"
