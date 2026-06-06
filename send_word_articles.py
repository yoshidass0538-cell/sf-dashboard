"""
ITワード解説記事 日替わり配信スクリプト（GitHub Actions用）

登録ワードから毎日3つ選び、各ワードの解説記事URL（使い方・解説中心に
キュレーション済み）を1本ずつ、指定のChatworkルームへ送信する。

2段ローテーション:
- どのワードか      = 通算日 ordinal×3+k（k=0..2）をワード数で割った余り
- そのワードの何本目 = ワード一覧を一巡するごとに次のURLへ進む（cycle % 本数）
これにより毎日ワードが入れ替わり、かつ数週間かけて記事も入れ替わる。
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


def pick(now: datetime):
    """通算日(ordinal)から当日分の (ワード, URL) を WORDS_PER_DAY 件決める。"""
    ordinal = now.date().toordinal()
    picks = []
    for k in range(WORDS_PER_DAY):
        idx = ordinal * WORDS_PER_DAY + k
        entry = WORDS[idx % len(WORDS)]
        cycle = idx // len(WORDS)
        url = entry["urls"][cycle % len(entry["urls"])]
        picks.append((entry, url))
    return picks


def build_body(picks: list) -> str:
    blocks = []
    for i, (entry, url) in enumerate(picks, 1):
        blocks.append(
            f"[info][title]今日のITワード解説 その{i}　{entry['word']}[/title]"
            f"{entry['desc']}\n\n"
            f"▼解説記事はこちら\n"
            f"{url}[/info]"
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

    now = datetime.now(JST)
    picks = pick(now)
    body = build_body(picks)

    words = " / ".join(entry["word"] for entry, _ in picks)
    print(f"--- {now.strftime('%Y/%m/%d')} {words} ---")
    print(body)
    print("--- Sending ---")
    send_chatwork(body, ROOM_ID)
    print("Done")


if __name__ == "__main__":
    main()
