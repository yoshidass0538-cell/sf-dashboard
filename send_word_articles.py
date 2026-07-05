"""
ITワード解説記事 日替わり配信スクリプト（GitHub Actions用）

配信ワードはGoogleスプレッドシート「使用URLまとめ」タブのA列から取得し、
毎日3つ選んで指定のChatworkルームへ送信する。

- シートのワードが下記WORDS（キュレーション済み記事URL辞書）にあれば、
  ワード＋説明＋記事URL1本を配信（記事はワード一巡ごとに次のURLへ進む）
- 辞書に無い新ワードは、ワード＋検索リンクを配信（URLは後から辞書に追加可能）
- シートが読めない場合はWORDS全件を母集団にして配信を継続（配信を止めない）

2段ローテーション:
- どのワードか      = 通算日 ordinal×3+k（k=0..2）をワード数で割った余り
- そのワードの何本目 = ワード一覧を一巡するごとに次のURLへ進む（cycle % 本数）
これにより毎日ワードが入れ替わり、かつ数週間かけて記事も入れ替わる。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

CHATWORK_API_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_API_URL = "https://api.chatwork.com/v2"
JST = timezone(timedelta(hours=9))

# 送信先ルームID
ROOM_ID = os.environ.get("WORD_ARTICLE_ROOM_ID", "REPLACE_WITH_ROOM_ID")

# ワード候補の取得元スプレッドシート（サービスアカウントに閲覧共有が必要）
WORD_SHEET_ID = os.environ.get(
    "WORD_SHEET_ID", "16AhaqFxneRacjAsOsRdrZXOdLTDlBwvc_ZbmHV0r03g"
)
WORD_SHEET_TAB = os.environ.get("WORD_SHEET_TAB", "使用URLまとめ")


def _sheet_credentials():
    """環境変数 GCP_SERVICE_ACCOUNT_JSON（Base64対応）またはローカル鍵ファイルから
    読み取り専用の認証情報を作る（send_hourly_summary.py と同じ方式）。"""
    import base64
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    sa_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        try:
            creds_dict = json.loads(base64.b64decode(sa_json))
        except Exception:
            creds_dict = json.loads(sa_json)
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    # ローカルフォールバック（キーファイル名は GCP_KEY_FILE 環境変数に統一）
    return Credentials.from_service_account_file(
        os.environ.get("GCP_KEY_FILE", ""), scopes=scopes
    )

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
    {
        "word": "システムプロンプト",
        "desc": "AIに役割・制約・ふるまいの土台を最初に与える指示文。出力の一貫性を決める。",
        "urls": [
            "https://shinjidainotobira.com/system-prompt/",
            "https://japan-ai.co.jp/media/5467/",
            "https://umarketing.co.jp/ai-glossary/system-prompt/",
            "https://a-x.inc/blog/llm-system-prompt/",
        ],
    },
    {
        "word": "ユーザープロンプト",
        "desc": "利用者がその場でAIに送る具体的な指示・依頼文。システムプロンプトとの違いも解説。",
        "urls": [
            "https://smarf.jp/article/20435/",
            "https://zenn.dev/lumichy/articles/system-vs-user-prompt-llm-guide",
            "https://qiita.com/free-honda/items/77e45095e4026fc7da75",
            "https://actionbridge.io/ja/llmtutorial/p/mcp-system-vs-user",
        ],
    },
    {
        "word": "AIエージェント",
        "desc": "目標に向け状況を認識し、自律的に判断・行動するAIシステム。生成AIとの違いも。",
        "urls": [
            "https://www.kagoya.jp/howto/engineer/hpc/aiagent/",
            "https://www.ai-souken.com/article/ai-agent-overview",
            "https://proactive.jp/resources/columns/ai-agent-guide/",
            "https://www.salesforce.com/jp/blog/jp-what-is-aiagent/",
        ],
    },
    {
        "word": "LLM（大規模言語モデル）",
        "desc": "ClaudeやChatGPTの土台となる、大量の言語データを学習したAIモデル。仕組みと種類。",
        "urls": [
            "https://aismiley.co.jp/ai_news/what-is-large-language-models/",
            "https://www.nec-solutioninnovators.co.jp/sp/contents/column/20240229_llm.html",
            "https://www.hitachi-solutions-create.co.jp/column/technology/llm.html",
            "https://www.skygroup.jp/media/article/4326/",
        ],
    },
    {
        "word": "トークン",
        "desc": "AIがテキストを処理する最小単位。API料金や文字数制限はトークン数で決まる。",
        "urls": [
            "https://a-x.inc/blog/llm-tokens/",
            "https://ex-ture.com/blog/2026/02/28/what-is-token/",
            "https://g-gen.co.jp/useful/General-tech/explain-language-generation-ai-token/",
            "https://data.wingarc.com/token-and-api-fees-71251",
        ],
    },
    {
        "word": "ハルシネーション",
        "desc": "AIが事実に基づかない情報をもっともらしく出力する現象。業務利用の最重要注意点。",
        "urls": [
            "https://www.softbank.jp/business/content/blog/202603/what-is-hallucination",
            "https://www.ai-souken.com/article/hallucination-overview",
            "https://business.ntt-east.co.jp/content/cloudsolution/municipality/column-31.html",
            "https://weel.co.jp/media/hallucination",
        ],
    },
    {
        "word": "RAG（検索拡張生成）",
        "desc": "社内文書など外部データを検索してAIに参照させ、正確な回答を生成させる仕組み。",
        "urls": [
            "https://www.dir.co.jp/world/entry/solution/rag",
            "https://www.helpfeel.com/blog/rag-generative-ai",
            "https://www.sei-info.co.jp/quicksolution/column/rag/",
            "https://jp.tdsynnex.com/blog/ai/what-is-rag-ai/",
        ],
    },
    {
        "word": "MCP（Model Context Protocol）",
        "desc": "AIと外部ツール・データをつなぐ標準規格。「AI用のUSB-Cポート」と呼ばれる。",
        "urls": [
            "https://business.ntt-east.co.jp/content/cloudsolution/ih_column-193.html",
            "https://hblab.co.jp/blog/what-is-mcp/",
            "https://www.ai-souken.com/article/mcp-overview",
            "https://jp.ext.hp.com/techdevice/ai/ai_explained_23/",
        ],
    },
    {
        "word": "ファインチューニング",
        "desc": "学習済みAIモデルを自社データで追加学習させ、特定業務に適応させる手法。RAGとの違いも。",
        "urls": [
            "https://www.sbbit.jp/article/cont1/133069",
            "https://biz.kddi.com/content/column/smartwork/what-is-fine-tuning/",
            "https://aismiley.co.jp/ai_news/fine-tuning-rag-difference/",
            "https://promo.digital.ricoh.com/ai-for-work/column/detail018/",
        ],
    },
    {
        "word": "API",
        "desc": "ソフトウェア同士が情報をやり取りする接続口。システム連携の基本の仕組み。",
        "urls": [
            "https://kwcplus.kddi-web.com/blog/what-is-api",
            "https://www.ntt.com/business/services/rink/knowledge/archive_18.html",
            "https://www.sbbit.jp/article/cont1/62752",
            "https://data.wingarc.com/what-is-api-16084",
        ],
    },
    {
        "word": "CI/CD",
        "desc": "コード変更を自動でテスト・本番反映する開発手法。GitHub Actionsが代表例。",
        "urls": [
            "https://atmarkit.itmedia.co.jp/ait/articles/2107/28/news014.html",
            "https://it-biz.online/it-skills/ci-cd/",
            "https://www.kagoya.jp/howto/it-glossary/develop/githubactions/",
            "https://s-p-net.com/knowledge/tech-knowledge/github-actions-cicd-fundamentals-and-design",
        ],
    },
    {
        "word": "リポジトリ",
        "desc": "ファイルと変更履歴をまとめて保存する場所。ローカル/リモートの2種類がある。",
        "urls": [
            "https://backlog.com/ja/git-tutorial/intro/02/",
            "https://ninjacode.work/magazine/programming/git4/",
            "https://envader.plus/article/553",
            "https://www.sejuku.net/blog/70775",
        ],
    },
    {
        "word": "DX（デジタルトランスフォーメーション）",
        "desc": "データとデジタル技術で業務・ビジネスモデルを変革すること。IT化との違いも解説。",
        "urls": [
            "https://www.nri.com/jp/knowledge/glossary/dx.html",
            "https://monstar-lab.com/dx/about/digital_transformation/",
            "https://biz.kddi.com/content/column/smartwork/what-is-digital-transformation/",
            "https://www.ntt.com/business/services/rink/knowledge/archive_24.html",
        ],
    },
    {
        "word": "PoC（概念実証）",
        "desc": "本格導入の前に小規模に試して実現可能性を検証する取り組み。AI導入で頻出。",
        "urls": [
            "https://www.ricoh.co.jp/magazines/smb/column/006953/",
            "https://www.nec-solutioninnovators.co.jp/sp/contents/column/20230414_poc.html",
            "https://monstar-lab.com/dx/about/about-poc/",
            "https://asana.com/ja/resources/proof-of-concept",
        ],
    },
]


WORDS_PER_DAY = 3


def fetch_sheet_words() -> list:
    """スプレッドシートA列（A1は見出しのためA2以下）からワード候補を取得する。
    失敗時は空リスト。"""
    try:
        from google.auth.transport.requests import AuthorizedSession

        sess = AuthorizedSession(_sheet_credentials())
        resp = sess.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{WORD_SHEET_ID}"
            f"/values/{quote(WORD_SHEET_TAB)}!A2:A",
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json().get("values", [])
    except Exception as e:
        print(f"WARN: sheet fetch failed: {e}")
        return []
    words = []
    for row in rows:
        w = (row[0] if row else "").strip()
        if w and w not in words:
            words.append(w)
    return words


def _norm(s: str) -> str:
    return re.sub(r"[\s　]", "", s or "").casefold()


def _build_lookup() -> dict:
    """WORDS辞書を「正規化ワード→エントリ」で引けるようにする。
    「Claude（クロード）」は「claude（クロード）」と「claude」の両方で引ける。"""
    lookup = {}
    for entry in WORDS:
        full = _norm(entry["word"])
        base = _norm(re.sub(r"[（(].*?[）)]", "", entry["word"]))
        for key in (full, base):
            if key:
                lookup.setdefault(key, entry)
    return lookup


def pick(now: datetime, words: list):
    """通算日(ordinal)から当日分の (表示ワード, 説明, URL) を WORDS_PER_DAY 件決める。"""
    lookup = _build_lookup()
    ordinal = now.date().toordinal()
    picks = []
    for k in range(WORDS_PER_DAY):
        idx = ordinal * WORDS_PER_DAY + k
        word = words[idx % len(words)]
        cycle = idx // len(words)
        entry = lookup.get(_norm(word))
        if entry:
            url = entry["urls"][cycle % len(entry["urls"])]
            picks.append((entry["word"], entry["desc"], url))
        else:
            # 辞書未登録の新ワード: 検索リンクで代替（URLは後からWORDSに追加できる）
            url = "https://www.google.com/search?q=" + quote(f"{word} とは わかりやすく")
            picks.append((word, "", url))
    return picks


def build_body(picks: list) -> str:
    blocks = []
    for i, (word, desc, url) in enumerate(picks, 1):
        if desc:
            body = f"{desc}\n\n▼解説記事はこちら\n{url}"
        else:
            body = f"▼解説記事を探して読んでみよう\n{url}"
        blocks.append(
            f"[info][title]今日のITワード解説 その{i}　{word}[/title]{body}[/info]"
        )
    return "\n".join(blocks)


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

    sheet_words = fetch_sheet_words()
    if sheet_words:
        print(f"sheet words: {len(sheet_words)}件")
    else:
        # シートが読めなくても配信は止めない（従来の内蔵リストで継続）
        print("WARN: falling back to built-in WORDS list")
        sheet_words = [entry["word"] for entry in WORDS]

    now = datetime.now(JST)
    picks = pick(now, sheet_words)
    body = build_body(picks)

    words = " / ".join(word for word, _, _ in picks)
    print(f"--- {now.strftime('%Y/%m/%d')} {words} ---")
    print(body)
    print("--- Sending ---")
    send_chatwork(body, ROOM_ID)
    print("Done")


if __name__ == "__main__":
    main()
