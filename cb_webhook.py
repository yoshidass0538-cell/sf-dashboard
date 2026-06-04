"""
CB対応アドバイザー Webhook受け口（Cloud Run / 任意のWSGIホスト用）

チャットワークWebhook(message_created)を受信し、署名検証→本文解析→
SF取得＋Claude生成(cb_advisor)→同ルームに返信する。

必要な環境変数:
- CHATWORK_API_TOKEN        返信用APIトークン
- CHATWORK_WEBHOOK_TOKEN    Webhook署名検証用トークン(チャットワークのWebhook設定で発行)
- CHATWORK_BOT_ACCOUNT_ID   Bot自身のアカウントID(自分の投稿を無視しループ防止)
- ANTHROPIC_API_KEY         Claude APIキー
- SF_USERNAME / SF_PASSWORD / SF_TOKEN  Salesforce認証
- CB_MODEL                  既定 claude-sonnet-4-6
- CB_ALLOWED_ROOM_IDS       任意。カンマ区切りで応答対象ルームを限定
"""

import os
import hmac
import json
import base64
import hashlib
import logging

import requests
from flask import Flask, request

import cb_advisor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

CHATWORK_API_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_WEBHOOK_TOKEN = os.environ.get("CHATWORK_WEBHOOK_TOKEN", "")
CHATWORK_BOT_ACCOUNT_ID = os.environ.get("CHATWORK_BOT_ACCOUNT_ID", "")
CB_ALLOWED_ROOM_IDS = {
    r.strip() for r in os.environ.get("CB_ALLOWED_ROOM_IDS", "").split(",") if r.strip()
}
CHATWORK_API_URL = "https://api.chatwork.com/v2"

_sf = None


def get_sf_cached():
    """SF接続をプロセス内でキャッシュ。失敗時は再接続。"""
    global _sf
    if _sf is None:
        from sf_client import get_sf
        _sf = get_sf()
    return _sf


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """チャットワークWebhook署名(HMAC-SHA256, Base64)を検証。"""
    if not CHATWORK_WEBHOOK_TOKEN or not signature:
        return False
    key = base64.b64decode(CHATWORK_WEBHOOK_TOKEN)
    digest = hmac.new(key, raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def reply_chatwork(room_id: str, body: str, to_account_id=None, message_id=None) -> None:
    prefix = ""
    if to_account_id and message_id:
        prefix = f"[rp aid={to_account_id} to={room_id}-{message_id}]\n"
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    resp = requests.post(
        f"{CHATWORK_API_URL}/rooms/{room_id}/messages",
        headers=headers,
        data={"body": prefix + body},
        timeout=15,
    )
    logger.info("reply room=%s status=%s", room_id, resp.status_code)


@app.get("/")
def health():
    return "ok", 200


@app.post("/chatwork-webhook")
def webhook():
    raw = request.get_data()
    sig = request.headers.get("X-ChatWorkWebhookSignature", "")
    if not verify_signature(raw, sig):
        logger.warning("invalid signature")
        return "invalid signature", 401

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return "bad json", 400

    if payload.get("webhook_event_type") != "message_created":
        return "ignored", 200

    ev = payload.get("webhook_event", {})
    room_id = str(ev.get("room_id", ""))
    message_id = ev.get("message_id")
    from_account_id = str(ev.get("from_account_id", ""))
    body = ev.get("body", "")

    # 自分(Bot)の投稿は無視＝ループ防止
    if CHATWORK_BOT_ACCOUNT_ID and from_account_id == str(CHATWORK_BOT_ACCOUNT_ID):
        return "self", 200
    # 二重ガード: Bot自身の返信([info]整形)は対象外
    if body.lstrip().startswith("[info]"):
        return "self-format", 200
    # 応答対象ルームの限定(設定時のみ)
    if CB_ALLOWED_ROOM_IDS and room_id not in CB_ALLOWED_ROOM_IDS:
        return "room not allowed", 200

    req = cb_advisor.parse_request(body)
    if not req:
        return "no match", 200  # 申番＋モードでなければ無反応

    try:
        sf = get_sf_cached()
        reply = cb_advisor.handle(sf, body)
    except Exception as e:
        logger.exception("handle failed")
        reply = (
            f"[info][title]{req['number']}[/title]"
            f"対応方針の生成中にエラーが発生しました（{type(e).__name__}）。"
            f"時間をおいて再度お試しください。[/info]"
        )

    if reply:
        reply_chatwork(room_id, reply, from_account_id, message_id)
    return "ok", 200


if __name__ == "__main__":
    # ローカル起動用。本番は gunicorn cb_webhook:app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
