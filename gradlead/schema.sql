CREATE TABLE IF NOT EXISTS universities (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    name_key        TEXT NOT NULL UNIQUE,
    country         TEXT,
    region          TEXT,
    city            TEXT,
    goal            INTEGER,              -- professors to discover (from targets.txt)
    notes           TEXT,                 -- where to look: departments, groups, programmes
    directory_urls  TEXT,                 -- JSON list of faculty directories the discoverer used
    openalex_id     TEXT,                 -- cached institution id (I…)
    discovered_at   TEXT,                 -- set when faculty discovery finished
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS professors (
    id                INTEGER PRIMARY KEY,
    university_id     INTEGER NOT NULL REFERENCES universities(id),
    full_name         TEXT NOT NULL,
    name_key          TEXT NOT NULL,
    title             TEXT,
    seniority         TEXT,
    department        TEXT,
    lab_name          TEXT,
    lab_url           TEXT,
    homepage          TEXT,
    profile_url       TEXT,                -- faculty directory entry
    source_url        TEXT,                -- where the discoverer saw them
    interests         TEXT,                -- JSON list (directory/homepage)
    summary           TEXT,                -- research focus in the profiler's words
    email             TEXT,
    email_source_url  TEXT,                -- REQUIRED with email: page where the address is published
    email_status      TEXT,                -- unchecked | confirmed | unconfirmed | invalid
    email_detail      TEXT,
    openalex_id       TEXT,
    s2_id             TEXT,
    topics            TEXT,                -- JSON list from OpenAlex
    status            TEXT NOT NULL DEFAULT 'discovered',
    status_note       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (university_id, name_key)
);
CREATE INDEX IF NOT EXISTS idx_prof_status ON professors(status);
CREATE INDEX IF NOT EXISTS idx_prof_openalex ON professors(openalex_id);

CREATE TABLE IF NOT EXISTS publications (
    id            INTEGER PRIMARY KEY,
    professor_id  INTEGER NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    title_key     TEXT NOT NULL,
    year          INTEGER,
    venue         TEXT,
    url           TEXT,
    doi           TEXT,
    abstract      TEXT,
    cited_by      INTEGER,
    source        TEXT,                   -- openalex | s2 | homepage
    UNIQUE (professor_id, title_key)
);

CREATE TABLE IF NOT EXISTS signals (
    professor_id        INTEGER PRIMARY KEY REFERENCES professors(id) ON DELETE CASCADE,
    accepting_students  TEXT,             -- yes | no | unknown
    accepting_quote     TEXT,
    accepting_url       TEXT,
    open_positions      TEXT,             -- JSON [{title, degree, funded, deadline, url}]
    emeritus            INTEGER DEFAULT 0,
    moved_to            TEXT,
    not_faculty         INTEGER DEFAULT 0,
    last_pub_year       INTEGER,
    works_count         INTEGER,
    cited_by_count      INTEGER,
    h_index             INTEGER,
    pages_read          TEXT,
    profiled_at         TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    professor_id      INTEGER PRIMARY KEY REFERENCES professors(id) ON DELETE CASCADE,
    score             INTEGER NOT NULL,
    classification    TEXT NOT NULL,       -- strong | good | weak
    primary_area      TEXT,
    areas             TEXT,                -- JSON {area: {score, terms, papers}}
    breakdown         TEXT,                -- JSON points per component
    matched_papers    TEXT,                -- JSON [publication ids], best hooks first
    matched_projects  TEXT,                -- JSON [project keys from applicant.json]
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id                    INTEGER PRIMARY KEY,
    professor_id          INTEGER NOT NULL UNIQUE REFERENCES professors(id) ON DELETE CASCADE,
    hook_publication_id   INTEGER REFERENCES publications(id),
    cv_project            TEXT,
    programme             TEXT,
    subject               TEXT NOT NULL,
    body                  TEXT NOT NULL,      -- includes the code-appended signature
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppressions (
    value       TEXT PRIMARY KEY,             -- lowercased email or domain
    reason      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    command     TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id               INTEGER PRIMARY KEY,
    url              TEXT NOT NULL UNIQUE,     -- the advert itself
    title            TEXT NOT NULL,
    institution      TEXT,
    university_id    INTEGER REFERENCES universities(id),
    country          TEXT,
    region           TEXT,
    degree           TEXT,                     -- PhD | MSc | MPhil | RA
    funded           INTEGER,                  -- 1 funded / salaried, 0 unfunded, NULL unknown
    deadline         TEXT,                     -- ISO date, NULL if rolling/unknown
    supervisor       TEXT,
    professor_id     INTEGER REFERENCES professors(id),
    description      TEXT,                     -- the ad text the score is computed from (trimmed)
    source           TEXT,                     -- euraxess | jobs.ac.uk | academicpositions | university | ...
    score            INTEGER,
    primary_area     TEXT,
    terms            TEXT,                     -- JSON matched terms
    status           TEXT NOT NULL,            -- relevant | weak | expired | unfunded
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_deadline ON positions(deadline);
