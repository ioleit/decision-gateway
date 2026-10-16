-- The decision cache. One row per answer; an answer is final and never replaced.
-- JSON columns hold canonical JSON text (sorted keys).

CREATE TABLE IF NOT EXISTS answers (
    key          TEXT PRIMARY KEY,  -- cache/key.py: sha256 of [model, requirements, wire]
    model        TEXT NOT NULL,     -- the name in models.toml
    requirements TEXT NOT NULL,     -- JSON: the model's requirements when it answered
    request      TEXT NOT NULL,     -- JSON: the request as the caller made it
    wire         TEXT,              -- JSON: what went over the network, if not the request
    response     TEXT NOT NULL,     -- JSON: the answer, in the router's response format
    raw          TEXT,              -- JSON: the reply as received, if not the response
    asked_at     TEXT,              -- UTC, ISO 8601; NULL if unknown (imported answers)
    cost         REAL,              -- what the call cost, if the backend reports it
    provenance   TEXT               -- JSON: backend details (generation id, provider, ...)
);

CREATE INDEX IF NOT EXISTS answers_model ON answers (model);

-- What a question is about, in the caller's terms: any JSON object. Several per answer
-- (the same question asked by two investigations); never used to find an answer.
CREATE TABLE IF NOT EXISTS labels (
    key    TEXT NOT NULL,
    labels TEXT NOT NULL,         -- JSON object
    UNIQUE (key, labels)
);
