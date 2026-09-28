# 自己成長型ルールベース Discord チャットボット
## 実装仕様書

**Version:** 0.1  
**Language:** Python 3.x  
**Frontend:** Discord  
**Backend:** discord.py  
**形態素解析:** SudachiPy  
**Database:** SQLite  
**LLM:** 使用しない

---

# 1. 概要

本システムは、ユーザーとの対話を通じて語彙と概念間の関係を蓄積していく、ルールベースの Discord チャットボットである。

一般的なLLMのように大量の知識を事前学習するのではなく、以下のサイクルによって知識ベースを構築する。

```text
ユーザー発話
    ↓
形態素解析
    ↓
既知語・未知語の判定
    ↓
未知語なら質問
    ↓
ユーザー回答
    ↓
概念・関係を登録
    ↓
以後の会話で利用
```

Botは自身の知識に不確実性がある場合、勝手に推測せずユーザーに確認する。

---

# 2. 設計目標

## 2.1 必須目標

- Discord上で会話できる
- 日本語をSudachiPyで形態素解析する
- 未知の語彙を検出する
- 未知語についてユーザーに質問する
- ユーザーの回答から概念を登録する
- 概念間の階層関係を保持する
- 同義語を複数登録できる
- 肯定・否定などの表現を正規化する
- Botが過去に学習した知識を次回以降利用する
- SQLiteのみで永続化する
- LLMを使用しない

## 2.2 将来的な拡張

- 概念間の一般的な関係
- 知識の信頼度
- 学習内容の訂正
- ユーザーごとの知識
- 知識の可視化
- 推論
- 文脈解析
- 複数単語からなる概念
- 知識のエクスポート・インポート

---

# 3. システム構成

```text
Discord
   │
   ▼
discord.py
   │
   ▼
Message Handler
   │
   ├── Conversation Manager
   │
   ├── SudachiPy
   │      │
   │      ▼
   │   Tokenizer
   │
   ├── Vocabulary Manager
   │
   ├── Knowledge Graph
   │
   └── Rule Engine
          │
          ▼
       SQLite
```

主要モジュール：

```text
bot/
├── main.py
├── config.py
├── discord_bot.py
│
├── parser.py
├── vocabulary.py
├── ontology.py
├── inference.py
├── conversation.py
├── rules.py
│
├── database.py
└── schema.sql
```

---

# 4. Discord Bot

## 4.1 使用ライブラリ

```text
discord.py
```

BotはDiscord Gatewayからメッセージを受信する。

基本的なイベント：

```python
@bot.event
async def on_message(message):
    ...
```

Bot自身の発言は処理対象外とする。

```python
if message.author.bot:
    return
```

---

# 5. 形態素解析

SudachiPyを使用する。

```python
from sudachipy import Dictionary

tokenizer = Dictionary().create()
```

入力：

```text
猫を飼いたい
```

解析結果の概念例：

```text
猫
を
飼う
たい
```

システムでは原則として以下を利用する。

- Surface
- Normalized form
- Dictionary form
- Part of speech

例えば：

```text
Surface: 猫
Normalized: 猫
POS: 名詞
```

```text
Surface: 飼い
Normalized: 飼う
POS: 動詞
```

---

# 6. 語彙と概念の分離

文字列としての「単語」と、Botが認識する「概念」は別物として扱う。

例えば、

```text
猫
ネコ
ねこ
```

は異なる文字列だが、同一概念として登録できる。

```text
Word
 ├── 猫
 ├── ネコ
 └── ねこ
       │
       ▼
    Concept: 猫
```

---

# 7. 概念モデル

概念は以下のように定義する。

```text
Concept
----------------
id
canonical_name
created_at
status
```

例：

```text
id: 42
canonical_name: 猫
status: ACTIVE
```

---

# 8. 語彙モデル

```text
Word
----------------
id
word
concept_id
word_type
created_at
```

例：

```text
猫   → Concept 42
ネコ → Concept 42
ねこ → Concept 42
```

`word_type` の例：

```text
NORMAL
SYNONYM
ALIAS
SYSTEM
```

---

# 9. 知識グラフ

概念間の関係は `relations` テーブルで管理する。

```text
Concept
   │
   │ Relation
   ▼
Concept
```

基本的な関係：

```text
SAME_AS
IS_A
PART_OF
HAS_A
RELATED_TO
```

Version 0.1では最低限、

```text
SAME_AS
IS_A
```

を実装する。

---

# 10. IS_A

`IS_A` は「～の一種である」を表す。

```text
猫 IS_A 動物
```

これは、

```text
猫 == 動物
```

ではない。

したがって、

```text
猫は動物？
```

には肯定できるが、

```text
動物は猫？
```

には否定できる。

---

# 11. SAME_AS

`SAME_AS` は概念が同一であることを表す。

```text
猫 SAME_AS ネコ
```

ただし実装上は、可能なら複数のConceptを作らず、同じConceptに複数のWordを関連付ける。

```text
Concept: 猫
 ├── 猫
 ├── ネコ
 └── ねこ
```

`SAME_AS` は将来的な知識グラフ拡張用として予約する。

---

# 12. 初期オントロジー

データベースには最低限の概念をプリセットする。

```text
存在
├── 生き物
├── 食べ物
├── 物
├── 場所
├── 人
├── 行動
└── 状態
```

さらに、

```text
生き物
├── 動物
└── 植物
```

などを登録してもよい。

初期データは `seed.sql` などで管理する。

---

# 13. SQLiteスキーマ

## concepts

```sql
CREATE TABLE concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## words

```sql
CREATE TABLE words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    concept_id INTEGER NOT NULL,
    word_type TEXT NOT NULL DEFAULT 'NORMAL',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (concept_id)
        REFERENCES concepts(id)
);
```

## relations

```sql
CREATE TABLE relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    predicate TEXT NOT NULL,
    object_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    confidence INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id)
        REFERENCES concepts(id),

    FOREIGN KEY (object_id)
        REFERENCES concepts(id)
);
```

---

# 14. 否定された知識

誤学習によってデータベースが壊れることを防ぐため、関係を削除するのではなく状態を変更する。

```text
ACTIVE
REJECTED
```

例：

```text
猫 IS_A 動物
```

を学習した後、

```text
Bot:
猫は動物のこと？

User:
違う
```

となった場合、

```text
relations
--------------------------------
猫 | IS_A | 動物 | REJECTED
```

とする。

---

# 15. 肯定・否定の語彙

肯定・否定は特別なIntentとして扱う。

## YES

```text
はい
うん
そう
そうです
正しい
合ってる
その通り
OK
```

## NO

```text
いいえ
いや
違う
違います
違うよ
そうじゃない
```

DBに登録してもよいが、Version 0.1ではシステム定義の辞書として実装してよい。

```python
YES_WORDS = {
    "はい",
    "うん",
    "そう",
    "そうです",
    "正しい",
    "合ってる",
}

NO_WORDS = {
    "いいえ",
    "いや",
    "違う",
    "違います",
    "そうじゃない",
}
```

---

# 16. 会話状態

Botは会話ごとに状態を持つ。

```text
ConversationState
```

状態：

```text
IDLE
ASK_DEFINITION
ASK_RELATION
ASK_CONFIRMATION
ASK_SYNONYM
```

会話状態があるときは、回答の代わりに「キャンセル」「中止」「中断」「やめる」「もういい」などを入力すると、その会話状態を破棄する。`cancel` と全角・半角の表記揺れにも対応し、Botは「会話を中断しました。」と返信する。状態がないときは通常の発話として扱う。

例：

```text
User:
猫飼いたい

Bot:
猫って何？

State:
ASK_DEFINITION
target:
猫
```

---

# 17. 状態管理単位

Version 0.1では、

```text
Discord Guild ID
Discord Channel ID
User ID
```

を組み合わせて会話コンテキストを識別する。

基本的には、

```text
guild_id + channel_id + user_id
```

をConversation IDとする。

将来的にはチャンネル全体で共有する会話コンテキストにも対応可能とする。

---

# 18. 未知語処理

入力：

```text
猫飼いたい
```

解析：

```text
猫
飼う
たい
```

DB検索：

```text
猫 → 未登録
```

この場合、

```text
ASK_DEFINITION
```

へ遷移する。

Bot：

```text
猫って何？
```

Embeddingが既知概念候補を提示した後、ユーザーが「該当しない」「どれも違う」などと返した場合、候補を破棄して `ASK_DEFINITION` に遷移し、「猫って何？」と定義を質問する。この状態ではEmbedding候補を使わず、次の回答を通常の定義対話として処理する。

---

# 19. 定義回答

ユーザー：

```text
動物
```

Botは回答を解析する。

既知概念：

```text
動物
```

なら、

```text
猫 IS_A 動物
```

を候補として生成する。

その後、必要に応じて確認する。

```text
猫は動物の一種ということですか？
```

ユーザー：

```text
はい
```

なら確定する。

---

# 20. より直接的な学習

ユーザーが、

```text
猫は動物
```

と明示した場合は、

```text
猫 IS_A 動物
```

を直接候補として生成する。

ユーザーが、

```text
猫は動物の一種
```

と言った場合も同様。

Version 0.1では完全な自然言語理解は実装せず、既知の構文パターンだけを処理する。

---

# 21. 等価性確認

未知語について曖昧性がある場合、Botは同義かどうかを確認する。

例：

```text
既知概念:
動物

未知語:
猫
```

Bot：

```text
「猫」は「動物」と同じ意味ですか？
```

User：

```text
違う
```

Bot：

```text
では、「猫」は「動物」の一種ですか？
```

User：

```text
そう
```

結果：

```text
猫 IS_A 動物
```

---

# 22. 質問生成

質問はルールベースで生成する。

```python
QUESTION_TEMPLATES = {
    "definition":
        "{word}って何？",

    "same_as":
        "{a}は{b}と同じ意味ですか？",

    "is_a":
        "{a}は{b}の一種ですか？",

    "confirm":
        "{a}は{b}ということで合っていますか？",
}
```

---

# 23. 知識検索

入力された単語からConceptを取得する。

```python
def lookup_word(word: str) -> Concept | None:
    ...
```

未知の場合：

```python
None
```

既知の場合：

```python
Concept
```

を返す。

---

# 24. 関係検索

```python
def get_relation(subject, predicate, object):
    ...
```

例えば、

```python
get_relation(cat, "IS_A", animal)
```

がACTIVEなら、

```text
True
```

を返す。

---

# 25. 推論

Version 0.1では単純な階層推論のみ実装する。

```text
猫 IS_A 動物
動物 IS_A 生き物
```

なら、

```text
猫 IS_A 生き物
```

を推論可能とする。

ただし推論結果そのものをDBに保存する必要はない。

```text
explicit relation
```

と

```text
inferred relation
```

を区別する。

---

# 26. 推論アルゴリズム

IS_Aについて深さ優先探索または幅優先探索を使用する。

```text
猫
 ↓
動物
 ↓
生き物
```

探索中に対象Conceptへ到達した場合、

```text
TRUE
```

とする。

循環参照を防ぐためVisited Setを使用する。

---

# 27. 発話処理パイプライン

```python
async def process_message(message):
    text = message.content

    tokens = parser.parse(text)

    intent = rules.detect_intent(tokens)

    state = conversation.get_state(message)

    if state:
        return await conversation.handle_state(
            state,
            tokens,
            message
        )

    concepts = vocabulary.lookup(tokens)

    result = inference.analyze(
        tokens,
        concepts
    )

    return await rules.respond(result)
```

---

# 28. 重要な処理優先順位

メッセージを処理するときは以下の順番とする。

```text
1. 会話状態の確認
2. YES / NOなどの回答判定
3. 明示的な関係表現の検出
4. 既知語の検索
5. 未知語の検出
6. 推論
7. 応答
```

特に1を最優先する。

Botが、

```text
猫って何？
```

と質問した直後の

```text
動物
```

を、通常の独立した発話として処理してはいけない。

---

# 29. 例：最初の学習

```text
User:
猫飼いたい

Bot:
猫って何？

User:
動物

Bot:
猫は動物の一種ですか？

User:
はい

Bot:
わかりました。
```

DB：

```text
Concept:
動物
猫

Relation:
猫 IS_A 動物
```

---

# 30. 例：再利用

次の会話：

```text
User:
猫好き

Bot:
猫は動物ですね。
```

Botは以前学習した

```text
猫 IS_A 動物
```

を利用できる。

---

# 31. 例：訂正

```text
User:
猫は動物？

Bot:
はい。

User:
違う
```

この場合、

```text
猫 IS_A 動物
```

をREJECTEDにする。

さらに、

```text
Bot:
では、猫と動物はどういう関係ですか？
```

と質問する。

---

# 32. ユーザーによる知識訂正

ユーザーが、

```text
猫は動物じゃない
```

などと明示した場合、

```text
negative relation
```

として扱う。

Version 0.1では否定知識そのものを別テーブルにする必要はなく、既存RelationをREJECTEDにする方式を採用する。

将来的には、

```text
NOT_IS_A
```

などの否定関係を追加する。

---

# 33. データベース初期化

起動時に、

```text
database.sqlite
```

が存在しなければ作成する。

その後、

```text
schema.sql
seed.sql
```

を適用する。

---

# 34. データベースアクセス

SQLiteへのアクセスは標準ライブラリの

```text
sqlite3
```

を使用する。

Version 0.1ではORMを使用しない。

理由：

- 構造が単純
- SQLを直接管理できる
- 知識グラフのクエリを理解しやすい
- 小規模Botに十分

---

# 35. トランザクション

知識を追加するときはトランザクションを使用する。

例えば、

```text
Concept作成
↓
Word作成
↓
Relation作成
```

を一つのトランザクションとして扱う。

途中で失敗した場合はROLLBACKする。

---

# 36. ログ

最低限以下をログ出力する。

```text
[INFO] Discord connected
[INFO] Message received
[INFO] Unknown word: 猫
[INFO] Asking definition: 猫
[INFO] Learned: 猫 IS_A 動物
[INFO] Relation rejected: 猫 IS_A 動物
```

学習系のログはデバッグ時に非常に重要。

---

# 37. ディレクトリ構成

```text
knowledge_bot/
│
├── main.py
├── config.py
├── requirements.txt
│
├── bot/
│   ├── __init__.py
│   ├── discord_bot.py
│   └── conversation.py
│
├── nlp/
│   ├── __init__.py
│   └── parser.py
│
├── knowledge/
│   ├── __init__.py
│   ├── vocabulary.py
│   ├── ontology.py
│   └── inference.py
│
├── rules/
│   ├── __init__.py
│   └── engine.py
│
├── database/
│   ├── __init__.py
│   ├── database.py
│   ├── schema.sql
│   └── seed.sql
│
├── data/
│   └── bot.sqlite3
│
└── tests/
    ├── test_parser.py
    ├── test_ontology.py
    ├── test_inference.py
    └── test_conversation.py
```

---

# 38. requirements.txt

```text
discord.py
SudachiPy
SudachiDict-core
```

SQLiteはPython標準ライブラリを使用するため追加パッケージ不要。

---

# 39. Version 0.1の実装範囲

最初の実装では以下だけを完成させる。

### 必須

- Discord接続
- メッセージ取得
- SudachiPyによる形態素解析
- SQLite接続
- Concept検索
- Word検索
- 未知語検出
- ASK_DEFINITION
- YES / NO判定
- `IS_A`
- `SAME_AS`相当の同義語登録
- `IS_A`階層推論
- 学習内容の永続化

### 後回し

- 高度な自然言語理解
- 複雑な文法解析
- LLM
- ベクトル検索
- Embedding
- 自動Web検索
- 複雑な知識推論

---

# 40. 最初に実装する動作テスト

以下の会話が成立することをVersion 0.1の完成条件とする。

```text
User:
猫飼いたい

Bot:
猫って何？

User:
動物

Bot:
猫は動物の一種ですか？

User:
はい

Bot:
わかりました。
```

その後、

```text
User:
猫は動物？

Bot:
はい。
```

さらに、

```text
User:
動物は猫？

Bot:
いいえ。
```

となること。

---

# 41. 設計上の重要な原則

### 原則1：知らないことを推測しない

```text
未知語
↓
質問
```

とする。

### 原則2：概念と文字列を分離する

```text
猫
ネコ
ねこ
```

を別々の文字列として扱いつつ、一つのConceptに関連付ける。

### 原則3：等価と包含を区別する

```text
猫 SAME_AS ネコ

猫 IS_A 動物
```

は異なる関係である。

### 原則4：誤った知識を完全削除しない

```text
ACTIVE
REJECTED
```

によって学習履歴を保持する。

### 原則5：質問中は通常の解析を行わない

```text
ASK_DEFINITION
ASK_RELATION
ASK_CONFIRMATION
```

などの状態を優先する。

---

# 42. 将来の拡張

知識グラフを拡張する場合は、

```text
IS_A
PART_OF
HAS_A
USED_FOR
LOCATED_IN
LIKES
DISLIKES
CAUSES
BEFORE
AFTER
```

などを追加する。

最終的には、

```text
猫
├── IS_A → 動物
├── PART_OF → 生き物
├── LIKES → 魚
├── LIVES_IN → 家
└── RELATED_TO → ペット
```

のような知識グラフへ発展させる。

また、現在の `IS_A` ツリーについても、内部実装は「ツリー」ではなく「有向グラフ」として扱う。

---

# 43. 将来的な自己成長サイクル

最終的には以下のループを実現する。

```text
             ┌──────────────┐
             │  Discord発話 │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ 形態素解析   │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │ 知識検索     │
             └──────┬───────┘
                    ↓
             ┌──────┴───────┐
             │              │
           既知            未知
             │              │
             ↓              ↓
          推論・回答      質問する
                            │
                            ↓
                       ユーザー回答
                            │
                            ↓
                       仮説を生成
                            │
                            ↓
                         確認する
                            │
                            ↓
                       知識として保存
                            │
                            └──────→ 知識検索
```

この構造を基本アーキテクチャとし、**Bot自身が知識を生成するのではなく、「不足している知識を発見してユーザーに尋ね、確認されたものだけを知識グラフへ追加する」**ことを本システムの中心的な設計思想とする。

> ELIZAを意識しているが、埋め込みを使ったセマンティック検索など、最新のAI技術も取り入れたい。
はい。その方向なら、**「ELIZA型のルールベース対話エンジンを中核にして、AIは認識・検索・曖昧性解消を補助する」**設計がかなり相性が良いです。

重要なのは、LLMに会話そのものを任せないことです。**知識の正本はSQLiteの知識グラフ、会話制御はルール、Embeddingは「候補を見つけるための検索器」**にします。

Sentence Transformers系のEmbeddingは、同義語・表記揺れ・意味的に近い表現の検索に使え、さらにbi-encoderで候補を絞ってCross-Encoderで再ランキングする構成も一般的です。

改訂版アーキテクチャ
Discord
   │
   ▼
discord.py
   │
   ▼
┌──────────────────────────────┐
│       Dialogue Engine        │
│                              │
│  ELIZA-like Rule Engine      │
│  Conversation State Machine  │
└──────────────┬───────────────┘
               │
               ▼
       ┌───────────────┐
       │   NLP Layer   │
       │               │
       │   SudachiPy   │
       └───────┬───────┘
               │
       ┌───────┴────────┐
       ▼                ▼
Lexical Search     Semantic Search
       │                │
       │          Embedding Model
       │                │
       └───────┬────────┘
               ▼
        Candidate Ranking
               │
               ▼
       ┌────────────────┐
       │ Knowledge Graph│
       │    SQLite      │
       └────────────────┘
役割分担
技術	役割
discord.py	Discord I/O
SudachiPy	日本語形態素解析
SQLite	知識・会話状態・学習履歴
ルールエンジン	会話の制御
Embedding	意味的に近い語・発話の検索
Cross-Encoder	必要なら候補の再評価
将来のLLM	任意。文章理解・質問生成など
つまり、

AIが知識を決めるのではなく、AIが「何が近そうか」を提案し、ルールエンジンが判断する

という構造です。

Embeddingを入れると何ができるか
例えばDBに、

猫
犬
自動車
食事
走る
があるとします。

ユーザーが、

ねこを飼ってみたい

と言った場合、SudachiPyだけなら

ねこ
飼う
たい
です。

文字列検索では「ねこ」と「猫」は別物です。

Embedding検索を追加すると、

query: ねこ

候補:
猫       0.93
犬       0.71
ペット   0.68
自動車   0.12
のような候補を得られます。

Sentence Transformersのsemantic searchは、語句そのものではなく意味的な近さを利用できるため、同義語・略語・表記揺れなどにも対応できます。

ただしEmbeddingの結果を即採用しない
ここがこのBotでは非常に重要です。

例えば、

猫
に対して、

動物     0.82
ペット   0.79
犬       0.77
となったとしても、

猫 IS_A 動物
を自動登録してはいけません。

Embeddingは、

「この概念と近そう」

と言っているだけだからです。

したがって、

Embedding
    ↓
候補生成
    ↓
ルールによる検証
    ↓
必要ならユーザーに質問
    ↓
確認
    ↓
SQLiteへ登録
とします。

これによって、意味検索による柔軟性と、ルールベースシステムの予測可能性を両立できます。

さらに面白い使い方：質問候補を探す
例えば未知語：

猫
が来たとします。

DBには、

動物
ペット
生き物
犬
哺乳類
が登録されています。

Embedding検索：

猫
 │
 ├─ 動物      0.91
 ├─ 哺乳類    0.87
 ├─ ペット    0.83
 ├─ 犬        0.79
 └─ 生き物    0.77
するとBotは、

「猫」は「動物」の一種ですか？

という質問を生成できます。

ユーザー：

はい

すると、

猫 IS_A 動物
を登録します。

つまりEmbeddingは知識そのものではなく、教師あり対話を効率化するための候補発見器になります。

ELIZAとの組み合わせ
ここでELIZA的な仕組みが活きます。

例えばユーザー：

最近猫を飼いたいんだ

ルール：

「～したい」
を検出すると、

興味・願望
という会話カテゴリに入れる。

さらに、

猫
が未知なら、

未知概念 → 学習質問
を優先する。

つまり、

ELIZA Rule
     │
     ├── 感情・意図
     ├── 質問
     ├── 話題
     └── 文型
          │
          ▼
     Knowledge Graph
          ▲
          │
     Embedding Search
となります。

「何を言っているか」と「何を知っているか」を分離する
これもかなり重要です。

例えば、

猫飼いたい

という文章について、

発話解析
intent = WANT
subject = 猫
action = 飼う
知識
猫 IS_A 動物
は別のデータです。

したがって、

Dialogue Representation

WANT(
    subject = 猫,
    action = 飼う
)
という一時的な意味表現を作り、それを知識グラフと組み合わせます。

Embedding DBはSQLiteと分離してもよい
最初から専用Vector DBを入れる必要はありません。

概念数が数千～数万程度なら、

SQLite
+
EmbeddingをBLOBとして保存
でも十分試作できます。

例えば：

CREATE TABLE embeddings (
    concept_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    FOREIGN KEY(concept_id)
        REFERENCES concepts(id)
);

検索時にEmbeddingをメモリへロードして、

cosine_similarity(query, vectors)

で検索します。

Sentence Transformersのドキュメントでも、小規模コーパスではEmbeddingを保持して類似度検索する方式が紹介されています。おおむね100万件程度までならこの単純な方式が利用可能とされています。

このBotなら、最初はこれで十分でしょう。

さらに高度化するならHybrid Search
最終的には、

             User Message
                  │
          ┌───────┴────────┐
          ▼                ▼
     Keyword Search    Embedding
          │                │
          └───────┬────────┘
                  ▼
             Candidate
                  │
                  ▼
             Re-ranking
                  │
                  ▼
            Rule Engine
にします。

例えば、

「ネコ」
なら、

文字列検索:
ネコ

Embedding:
猫
ねこ
ペット
という両方の結果を統合できます。

これによって完全一致・形態素・意味検索の長所を組み合わせることができます。

Cross-Encoderも将来的に入れられる
候補が増えた場合、

Embedding
↓
Top 20
↓
Cross-Encoder
↓
Top 3
という二段階検索にできます。

Sentence Transformersでも、このbi-encoderによる候補取得→Cross-Encoderによる再ランキングという構成が推奨されています。

ただし、このBotの初期段階では不要です。

改訂版の技術スタック
元の仕様書を拡張するなら、

必須
────────────────────────
Python
discord.py
SudachiPy
SQLite

AI/NLP
────────────────────────
sentence-transformers
PyTorch
Embedding Model

将来
────────────────────────
Cross-Encoder
FAISS / hnswlib / SQLite vector extension
とします。

ただし、Embeddingモデル自体は外部APIではなくローカルモデルを推奨します。

このBotのコンセプトは「自分との会話から成長するBot」なので、検索のためにユーザー発話を外部サービスへ送らない構成の方が設計思想にも合っています。

最終的な思想
このBotを単なる「ELIZA + Embedding」にするより、

「Symbolic Core + Neural Retrieval」

として設計すると非常に面白くなります。

              ┌──────────────────┐
              │  Neural System   │
              │                  │
              │   Embedding      │
              │   Similarity     │
              │   Reranking      │
              └────────┬─────────┘
                       │
                    候補
                       │
                       ▼
              ┌──────────────────┐
              │ Symbolic System  │
              │                  │
              │ Rules            │
              │ Ontology         │
              │ State Machine    │
              │ Inference        │
              └────────┬─────────┘
                       │
                     確定
                       │
                       ▼
              ┌──────────────────┐
              │     SQLite       │
              │                  │
              │ Knowledge Graph  │
              │ Vocabulary       │
              │ Conversation     │
              └──────────────────┘
**「Embeddingは直感、ルールエンジンは論理、SQLiteは記憶」**という役割分担です。

この設計なら、ELIZAのような「機械的だけれど、内部状態を持っていて会話によって変化する」面白さを残しながら、現代的なEmbeddingによって「猫」「ねこ」「ネコ」や、「映画を見たい」「映画鑑賞したい」のような意味的な近さも扱えるようになります。

