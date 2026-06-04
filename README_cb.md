# CB対応アドバイザー（チャットワーク自動返信）デプロイ手順

チャットワークに「申込受付番号＋モード」を送ると、Salesforceの履歴をもとに
Claudeが対応方針を生成して即時返信するBot。

## 使い方（運用イメージ）
チャットワークの対象ルームで以下を送信:
```
申込受付番号：sontN26020222359
アドバイス        ← 今後どう対応すべきか（前向きな打ち手）
```
```
申込受付番号：sontN26020222359
FB               ← 過去対応の振り返り（こうすればよかった）
```
→ Botが [info] 形式で返信。

## 構成
- `cb_judgment_axis.md` … 代表方針（システムプロンプト）。ここを直せば判断基準を調整できる
- `cb_advisor.py` … 解析→SF取得→Claude生成→返信文（ホスティング非依存）
- `cb_webhook.py` … チャットワークWebhook受け口（Flask）
- `Dockerfile.cb` / `cb_requirements.txt` … Cloud Run用

## ローカル動作確認（生成だけ試す）
```
set ANTHROPIC_API_KEY=sk-ant-...
set SF_USERNAME=...  & set SF_PASSWORD=...  & set SF_TOKEN=...
python cb_advisor.py sontN26020222359 アドバイス
```

## Cloud Runデプロイ
前提: GCPプロジェクト・課金有効・gcloud認証済。

```bash
gcloud run deploy cb-advisor \
  --source . \
  --dockerfile Dockerfile.cb \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars CB_MODEL=claude-sonnet-4-6 \
  --set-secrets ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,\
CHATWORK_API_TOKEN=CHATWORK_API_TOKEN:latest,\
CHATWORK_WEBHOOK_TOKEN=CHATWORK_WEBHOOK_TOKEN:latest,\
SF_USERNAME=SF_USERNAME:latest,SF_PASSWORD=SF_PASSWORD:latest,SF_TOKEN=SF_TOKEN:latest \
  --set-env-vars CHATWORK_BOT_ACCOUNT_ID=<BotのアカウントID>,CB_ALLOWED_ROOM_IDS=<対象ルームID>
```
※ Secret Manager に各値を登録しておくこと（`gcloud secrets create ...`）。
デプロイ後に払い出される URL の末尾に `/chatwork-webhook` を付けたものが受信エンドポイント。

## チャットワーク側Webhook設定
1. チャットワークにBot用アカウント（または既存の送信用アカウント）でログイン
2. サービス連携 → Webhook → 新規作成
3. 受信イベント: 「メッセージ作成」、対象ルームを指定
4. URL: `https://<CloudRunのURL>/chatwork-webhook`
5. 発行された **Webhookトークン** を Secret `CHATWORK_WEBHOOK_TOKEN` に登録
6. Botアカウントを対象ルームに参加させる（SF/CB案件を扱う非公開ルーム推奨）

## 必要な前提（要準備）
- [ ] Anthropic APIキー（課金有効）
- [ ] 受信用ルームID（CB案件を扱う非公開ルーム）
- [ ] Botアカウント（返信主体）のアカウントID
- [ ] GCPで Cloud Run + Secret Manager 利用可能

## コスト目安（Sonnet 4.6・1件≒1万in/1千out）
約¥7/件 → 1日50件で約¥350/日（月約¥10,500）。Cloud Runは無料枠内でほぼ¥0。

## 品質メモ
- 自動生成は初期、手作業の精度には届かない（特に微妙判断）。
- `cb_judgment_axis.md` を運用しながら追記・調整して精度を上げる。
- 難件のみ `CB_MODEL=claude-opus-4-8` に切り替える運用も可。
