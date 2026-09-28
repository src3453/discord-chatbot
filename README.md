## 自己成長型ルールベース Discord チャットボット

`spec.md` の Version 0.1 を実装した Python / discord.py / SudachiPy / SQLite の Bot です。会話生成に LLM は使いません。

## 起動

Python 3.10 以降を用意し、LM Studio に `lmstudio-community/embeddinggemma-300m-qat-GGUF` をダウンロードしてロードします。LM Studio の Local Server を起動し、OpenAI互換 API をポート `1234` で待ち受けてください。

```powershell
py -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# .env の DISCORD_BOT_TOKEN を設定してから起動
py main.py
```

Discord Developer Portal で Message Content Intent を有効にしてください。初回起動時に `data/bot.sqlite3` を作成し、`database/schema.sql` と `database/seed.sql` を適用します。保存先は `DATABASE_PATH` 環境変数で変更できます。

`python-dotenv` が起動時に `.env` を読み込みます。シェルで既に設定された環境変数は `.env` の値より優先されます。`.env` はGit管理対象外で、秘密情報を含まない `.env.example` を初期設定に使います。

## 知識グラフ表示

コマンドラインからPNGを生成できます。

```powershell
py main.py graph --output knowledge_graph.png
```

Discord では `/knowledge_graph` を実行すると、概念・同義語・有効な関係を描画したPNGが返信されます。コマンドを表示するには、Botの招待時に `applications.commands` scopeも有効にしてください。

## 反応チャンネルと語彙管理

Botの通常メッセージ反応は既定で全チャンネルOFFです。サーバー内の対象チャンネルでチャンネル管理権限を持つユーザーが `/reaction_channel enabled:true` を実行すると有効になり、`enabled:false` で停止します。DMには反応しません。

`/forget_word word:<語彙>` は削除内容のプレビューを返します。共有知識への影響を確認した後、`confirm:true` で再実行してください。サーバー管理権限が必要で、削除は全サーバー共通の知識DBに適用されます。同義語だけならその表記を削除し、代表語を削除するときは別名を新しい代表語に昇格します。代表語以外がない概念は、接続する関係とともに削除します。システム定義語は削除できません。

## LM Studio Embedding

未登録語を検出すると、Bot は LM Studio の `POST /v1/embeddings` に問い合わせ、類似度の高い既知概念を最大3件提示します。ユーザーが候補を選び、同義・`IS_A`・`RELATED_TO` 関係を確認するまで知識には登録しません。「該当しない」「どれも違う」などの返答では候補を破棄し、Embeddingを使わない定義質問に切り替えます。Embedding は `embeddings` SQLite テーブルにモデルIDとともに保存し、再利用します。LM Studio が利用できない場合も従来の定義質問に戻ります。

`RELATED_TO` は「似た言葉」の水平・対称な関係です。`SAME_AS` の同義関係や `IS_A` の階層関係とは別で、推論には使いません。Botが関係を尋ねた際に「似た言葉」と答えると確認質問を行い、肯定後に両方向を記録します。ネットワーク図では矢印なしの辺として表示します。

| 環境変数 | 既定値 | 用途 |
| --- | --- | --- |
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234/v1` | ローカルAPIのBase URL（loopbackのみ許可） |
| `LM_STUDIO_EMBEDDING_MODEL` | `text-embedding-embeddinggemma-300m-qat` | LM Studioのロード済みモデルID |
| `LM_STUDIO_API_KEY` | `lm-studio` | LM Studio APIキー |
| `EMBEDDING_MIN_SIMILARITY` | `0.45` | 候補表示のコサイン類似度しきい値（0〜1） |

EmbeddingGemma の検索用クエリ／文書指示を付けてベクトル化します。送信するのは抽出済みの未知語と既知語だけで、loopbackのLM Studio以外へ発話を送信しません。

## 会話のキャンセル

質問への回答を待っている間に「キャンセル」「中止」「中断」「やめる」「もういい」または `cancel` と入力すると、そのユーザーの現在の会話状態を破棄します。「会話を中断してください」のような表現や全角・半角の違いも認識します。Botは「会話を中断しました。」と返信し、以後の発話は新しい会話として扱います。

## 検証

```powershell
py -m unittest discover -v
```

API仕様: [LM Studio Embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings)。モデルのタスク指示: [EmbeddingGemma model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card)。
