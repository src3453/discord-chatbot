PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'REJECTED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    concept_id INTEGER NOT NULL,
    word_type TEXT NOT NULL DEFAULT 'NORMAL' CHECK (word_type IN ('NORMAL', 'SYNONYM', 'ALIAS', 'SYSTEM')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (concept_id) REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS embeddings (
    word TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (word) REFERENCES words(word) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS embeddings_model
    ON embeddings(model);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    predicate TEXT NOT NULL,
    object_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'REJECTED')),
    confidence INTEGER NOT NULL DEFAULT 100 CHECK (confidence BETWEEN 0 AND 100),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES concepts(id),
    FOREIGN KEY (object_id) REFERENCES concepts(id),
    UNIQUE (subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS relations_subject_predicate_status
    ON relations(subject_id, predicate, status);
CREATE INDEX IF NOT EXISTS relations_object_predicate_status
    ON relations(object_id, predicate, status);

CREATE TABLE IF NOT EXISTS reaction_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);
