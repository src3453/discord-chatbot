INSERT OR IGNORE INTO concepts (canonical_name) VALUES
    ('存在'), ('生き物'), ('食べ物'), ('物'), ('場所'), ('人'), ('行動'), ('状態'), ('動物'), ('植物');

INSERT OR IGNORE INTO words (word, concept_id, word_type)
SELECT canonical_name, id, 'SYSTEM' FROM concepts
WHERE canonical_name IN ('存在', '生き物', '食べ物', '物', '場所', '人', '行動', '状態', '動物', '植物');

INSERT OR IGNORE INTO relations (subject_id, predicate, object_id)
SELECT child.id, 'IS_A', parent.id
FROM concepts AS child, concepts AS parent
WHERE (child.canonical_name = '生き物' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '食べ物' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '物' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '場所' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '人' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '行動' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '状態' AND parent.canonical_name = '存在')
   OR (child.canonical_name = '動物' AND parent.canonical_name = '生き物')
   OR (child.canonical_name = '植物' AND parent.canonical_name = '生き物');
