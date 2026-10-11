-- GENERATED from api/cookiemonsters/storage/sql.py by tools/sync_generated.py.
-- Apply with: npx wrangler d1 migrations apply cookiemonsters --remote

CREATE TABLE IF NOT EXISTS site_week (
  site TEXT NOT NULL,
  week TEXT NOT NULL,
  scoring_version INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  hist TEXT NOT NULL DEFAULT '{}',
  outcomes TEXT NOT NULL DEFAULT '{}',
  flags TEXT NOT NULL DEFAULT '{}',
  cmps TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (site, week, scoring_version)
);

CREATE TABLE IF NOT EXISTS sites (
  site TEXT PRIMARY KEY,
  prefix TEXT NOT NULL,
  first_week TEXT NOT NULL,
  last_week TEXT NOT NULL,
  refreshed_week TEXT NOT NULL,
  reports INTEGER NOT NULL,
  score INTEGER NOT NULL,
  record TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sites_prefix ON sites (prefix);

CREATE INDEX IF NOT EXISTS sites_last_week ON sites (last_week, site);

CREATE INDEX IF NOT EXISTS sites_score ON sites (score, site);

CREATE TABLE IF NOT EXISTS day_salt (
  day TEXT PRIMARY KEY,
  salt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rate (
  day TEXT NOT NULL,
  k TEXT NOT NULL,
  n INTEGER NOT NULL,
  PRIMARY KEY (day, k)
);
