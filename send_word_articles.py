"""
ITワード解説記事 日替わり配信スクリプト（GitHub Actions用）

8ワードを日替わりで1つ選び、そのワードの解説記事URL（使い方・解説中心に
キュレーション済み）を1本、指定のChatworkルームへ毎日送信する。

2段ローテーション:
- どのワードか      = 通算日 ordinal を 8 で割った余り
- そのワードの何本目 = 8日で一巡するごとに次のURLへ進む（cycle % 本数）
これにより毎日ワードが変わり、かつ数週間かけて記事も入れ替わる。
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import requests

CHATWORK_API_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_API_URL = "https://api.chatwork.com/v2"
JST = timezone(timedelta(hours=9))

# 送信先ルームID
ROOM_ID = os.environ.get("WORD_ARTICLE_ROOM_ID", "REPLACE_WITH_ROOM_ID")

# --- ワード × 解説記事URL（使い方・解説中心にキュレーション） ---
WORDS = [
    {
        "word": "Claude（クロード）",
        "desc": "Anthropic製の会話型AI。登録方法から業務活用まで。",
        "urls": [
            "https://www.canva.com/ja_jp/learn/how-to-use-claude/",
            "https://www.lion-ai.co.jp/articles/ai-claude",
            "https://tenbin.ai/media/generative_ai/claude-full-guide",
            "https://romptn.com/article/67116",
        ],
    },
    {
        "word": "プラグイン化",
        "desc": "機能を差し替え・追加できる拡張の仕組み。",
        "urls": [
            "https://e-words.jp/w/%E3%83%97%E3%83%A9%E3%82%B0%E3%82%A4%E3%83%B3.html",
            "https://ja.wikipedia.org/wiki/%E3%83%97%E3%83%A9%E3%82%B0%E3%82%A4%E3%83%B3",
            "https://medium-company.com/%E3%83%97%E3%83%A9%E3%82%B0%E3%82%A4%E3%83%B3/",
            "https://pitta-lab.com/posts/623964",
        ],
    },
    {
        "word": "ROI（投資利益率）",
        "desc": "投資に対しどれだけ利益が出たかを測る指標。計算式と目安。",
        "urls": [
            "https://www.freee.co.jp/kb/kb-accounting/roi/",
            "https://www.nec-solutioninnovators.co.jp/sp/contents/column/20221216_roi.html",
            "https://www.zoho.com/jp/crm/academy/conceptual/roi/",
            "https://www.ricoh.co.jp/magazines/smb/column/006961/",
        ],
    },
    {
        "word": "AIOps",
        "desc": "AIでIT運用を自動化・最適化する手法。仕組みと活用例。",
        "urls": [
            "https://www.splunk.com/ja_jp/blog/artificial-intelligence/aiops.html",
            "https://www.hitachi-solutions-create.co.jp/column/technology/aiops.html",
            "https://www.nttpc.co.jp/column/ai/aiops.html",
            "https://www.ogis-ri.co.jp/column/cloud_arch/c106668.html",
        ],
    },
    {
        "word": "ハーネスエンジニアリング",
        "desc": "AIエージェントが正しく働ける環境・文脈・評価を設計する手法。",
        "urls": [
            "https://jp.findy-team.io/blog/ai-casestudy/harness-engineering/",
            "https://www.elcamy.com/blog/harness-engineering-guide",
            "https://blog.serverworks.co.jp/harness-engineering-overview",
            "https://www.hexabase.com/column/harness-engineering-complete-guide-ai-agent-3-elements-practical-steps",
        ],
    },
    {
        "word": "コンテキストエンジニアリング",
        "desc": "LLMに与える情報セットを設計・制御し出力精度を高める技術。",
        "urls": [
            "https://zenn.dev/acntechjp/articles/92e5402ad55bb0",
            "https://n-v-l.co/blog/context-engineering-beyond-prompt",
            "https://tech.algomatic.jp/entry/2025/10/15/172110",
            "https://zenn.dev/farstep/articles/context-engineering",
        ],
    },
    {
        "word": "プロンプトエンジニアリング",
        "desc": "生成AIから狙い通りの回答を得るための質問設計の技術。",
        "urls": [
            "https://www.skillupai.com/blog/ai-knowledge/chatgpt-prompt-engineering/",
            "https://miralab.co.jp/media/prompt-engineering/",
            "https://japan-ai.co.jp/media/6817/",
            "https://exawizards.com/column/article/dx/prompt-engineering/",
        ],
    },
    {
        "word": "GitHub",
        "desc": "Gitベースのコード共有・バージョン管理サービス。基本操作入門。",
        "urls": [
            "https://www.kagoya.jp/howto/it-glossary/develop/howtousegithub/",
            "https://www.sejuku.net/blog/73468",
            "https://envader.plus/article/68",
            "https://it-biz.online/it-skills/github/",
        ],
    },
]


def pick(now: datetime):
    """通算日(ordinal)から (ワード, URL) を決める。"""
    ordinal = now.date().toordinal()
    word_idx = ordinal % len(WORDS)
    cycle = ordinal // len(WORDS)
    entry = WORDS[word_idx]
    url = entry["urls"][cycle % len(entry["urls"])]
    return entry, url


def build_body(entry: dict, url: str) -> str:
    return (
        f"[info][title]今日のITワード解説　{entry['word']}[/title]"
        f"{entry['desc']}\n\n"
        f"▼解説記事はこちら\n"
        f"{url}[/info]"
    )


def send_chatwork(body: str, room_id: str) -> None:
    headers = {
        "X-ChatWorkToken": CHATWORK_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    resp = requests.post(
        f"{CHATWORK_API_URL}/rooms/{room_id}/messages",
        headers=headers,
        data={"body": body, "self_unread": 1},
        timeout=10,
    )
    print(f"Room {room_id}: {resp.status_code} {resp.text}")
    resp.raise_for_status()


def main():
    if not CHATWORK_API_TOKEN:
        print("ERROR: CHATWORK_API_TOKEN not set")
        sys.exit(1)
    if not ROOM_ID or ROOM_ID == "REPLACE_WITH_ROOM_ID":
        print("ERROR: WORD_ARTICLE_ROOM_ID not set")
        sys.exit(1)

    now = datetime.now(JST)
    entry, url = pick(now)
    body = build_body(entry, url)

    print(f"--- {now.strftime('%Y/%m/%d')} {entry['word']} ---")
    print(body)
    print("--- Sending ---")
    send_chatwork(body, ROOM_ID)
    print("Done")


if __name__ == "__main__":
    main()
