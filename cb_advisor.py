"""
CB対応アドバイザー 中核ロジック（ホスティング非依存）

チャットワークから「申込受付番号＋モード(アドバイス/FB)」を受け取り、
SalesforceのAccount/Task履歴を取得し、判断軸(cb_judgment_axis.md)を
システムプロンプトとしてClaude APIで対応方針を生成する。

2モード:
- "アドバイス" : 今の状況を踏まえて、これからどう対応すべきかの前向きな打ち手
- "FB"        : 過去に起きた対応の振り返り（こうすればよかった）＝従来C列スタイル

このモジュールはWebアプリ(cb_webhook.py)からもCLIからも呼べる。
SFは読み取り専用。
"""

import os
import re
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CB_MODEL = os.environ.get("CB_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_AXIS_PATH = Path(__file__).with_name("cb_judgment_axis.md")

# 入力履歴が長すぎる場合の安全上限（トークン暴発防止）
MAX_TASKS = 60
MAX_DESC_CHARS = 1500


# --- 判断軸の読み込み ---
def load_axis() -> str:
    return _AXIS_PATH.read_text(encoding="utf-8")


# --- 1) メッセージ解析 ---
# 例:
#   申込受付番号：sontN26020222359
#   アドバイス
# チャットワークのタグ([To:..],[rp ..],[qt]等)は除去してから解析する。
_TAG_RE = re.compile(r"\[/?[^\]]*\]")
_NUM_RE = re.compile(r"(?:申込受付番号|申番|受付番号)\s*[:：]?\s*([0-9A-Za-z\-_]+)")
_ADVICE_RE = re.compile(r"アドバイス|advice", re.IGNORECASE)
_FB_RE = re.compile(r"(?:^|\b|\s)(?:FB|ＦＢ|フィードバック|feedback)(?:$|\b|\s)", re.IGNORECASE)


def parse_request(body: str) -> dict | None:
    """メッセージ本文から {番号, モード} を抽出。該当しなければNone。"""
    text = _TAG_RE.sub(" ", body or "")
    m = _NUM_RE.search(text)
    if not m:
        # 「番号：」ラベルが無くても sontN... 形式があれば拾う
        m2 = re.search(r"\b(sont[0-9A-Za-z]+)\b", text, re.IGNORECASE)
        if not m2:
            return None
        number = m2.group(1)
    else:
        number = m.group(1)

    if _ADVICE_RE.search(text):
        mode = "アドバイス"
    elif _FB_RE.search(text):
        mode = "FB"
    else:
        return None  # 番号はあるがモード指定なし → 無反応

    return {"number": number, "mode": mode}


# --- 2) Salesforce取得（読み取り専用） ---
def fetch_case(sf, number: str) -> dict:
    """申込受付番号からAccountを特定し、Task履歴を時系列で取得。"""
    safe = re.sub(r"[^0-9A-Za-z\-_]", "", number)
    res = sf.search(f"FIND {{{safe}}} IN ALL FIELDS RETURNING Account(Id, Name)")
    records = res.get("searchRecords", []) if isinstance(res, dict) else (res or [])
    if not records:
        return {"found": False, "number": number}

    acc = records[0]
    account_id = acc["Id"]
    account_name = acc.get("Name", "")

    tasks = sf.query_all(
        "SELECT Subject, ActivityDate, CreatedDate, Status, Description, "
        "Owner.Name, TaskSubtype, CallType, CallDurationInSeconds "
        f"FROM Task WHERE WhatId = '{account_id}' ORDER BY CreatedDate"
    )["records"]

    return {
        "found": True,
        "number": number,
        "account_id": account_id,
        "account_name": account_name,
        "tasks": tasks[:MAX_TASKS],
        "task_total": len(tasks),
    }


def format_case(case: dict) -> str:
    """Claudeに渡すための案件テキストを組み立てる。"""
    lines = [
        f"申込受付番号: {case['number']}",
        f"顧客名: {case.get('account_name', '')}",
        f"活動記録(Task)件数: {case.get('task_total', 0)}",
        "",
        "=== 活動記録（時系列） ===",
    ]
    for t in case.get("tasks", []):
        date = t.get("ActivityDate") or (t.get("CreatedDate") or "")[:10]
        owner = (t.get("Owner") or {}).get("Name", "") if isinstance(t.get("Owner"), dict) else ""
        subj = t.get("Subject") or ""
        desc = (t.get("Description") or "").strip()
        if len(desc) > MAX_DESC_CHARS:
            desc = desc[:MAX_DESC_CHARS] + "…(以下略)"
        head = f"[{date}] {owner} / {subj}".strip()
        lines.append(head)
        if desc:
            lines.append(desc)
        lines.append("")
    return "\n".join(lines)


# --- 3) プロンプト生成（2モード） ---
_COMMON_RULES = (
    "あなたは光回線販売代理店のCB（キャッシュバック）対応の責任者AIです。"
    "下記『判断軸（代表方針）』に厳密に従い、実際の活動記録だけを根拠に判断してください。"
    "判断軸にない事項を勝手に創作しないこと。エントリー日が2026/5/1以前か以降かで"
    "チャージバック有無が変わる点、消センが『確定』か『検討段階』かの区別、"
    "OPがうちサポ(例外)かソネット側CPかの区別を特に正確に扱うこと。"
    "活動記録から日付・金額・経緯が読み取れない場合は『記録から確認できない』と明記し、推測で断定しない。"
)

_MODE_INSTRUCTION = {
    "アドバイス": (
        "【出力モード：アドバイス（今後の打ち手）】\n"
        "現在の状況を踏まえ、これから担当者がどう対応すべきかを助言してください。\n"
        "出力構成:\n"
        "1. 現状サマリー（商材／エントリー日と5/1基準／開通・決済の有無／争点）\n"
        "2. 今すぐ取るべき対応（突っぱねる／一部CB／月ずらし等を、判断軸の根拠付きで具体的に）\n"
        "3. 想定される顧客の反論と切り返しトーク\n"
        "4. CB範囲の線引き（出す/出さない項目を明確に）"
    ),
    "FB": (
        "【出力モード：FB（過去対応の振り返り）】\n"
        "既に行われた対応を評価し、本来どうすべきだったかをフィードバックしてください。\n"
        "出力構成:\n"
        "1. 経緯サマリー（時系列・担当者・実際に出したCB）\n"
        "2. 評価（適切／不適切／微妙）と理由（判断軸の該当項目を引用）\n"
        "3. 本来の正しい対応（こうすればCBを節制できた等、具体的に）\n"
        "4. 再発防止の教訓"
    ),
}


def build_messages(case: dict, mode: str) -> tuple[list, str]:
    """Claude API用の (system, user) を返す。systemはキャッシュ対象。"""
    axis = load_axis()
    system = [
        {"type": "text", "text": _COMMON_RULES},
        {
            "type": "text",
            "text": axis,
            "cache_control": {"type": "ephemeral"},  # 判断軸は固定→キャッシュ
        },
    ]
    user = (
        f"{_MODE_INSTRUCTION[mode]}\n\n"
        f"以下の案件について、上記モードで対応方針を作成してください。\n\n"
        f"{format_case(case)}"
    )
    return system, user


# --- 4) Claude API生成 ---
def generate(case: dict, mode: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")
    from anthropic import Anthropic

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system, user = build_messages(case, mode)
    resp = client.messages.create(
        model=CB_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


# --- 5) 返信文の組み立て ---
def build_reply(case: dict, mode: str, advice: str) -> str:
    label = "今後の対応アドバイス" if mode == "アドバイス" else "過去対応のFB"
    return (
        f"[info][title]{case['number']}　{label}[/title]"
        f"{advice}[/info]"
    )


def handle(sf, body: str) -> str | None:
    """本文を受け取り、返信本文を返す。対象外メッセージはNone。"""
    req = parse_request(body)
    if not req:
        return None
    case = fetch_case(sf, req["number"])
    if not case["found"]:
        return (
            f"[info][title]{req['number']}[/title]"
            f"申込受付番号に該当する案件がSalesforceで見つかりませんでした。"
            f"番号をご確認ください。[/info]"
        )
    advice = generate(case, req["mode"])
    return build_reply(case, req["mode"], advice)


# --- CLI（ローカルテスト用） ---
# 使い方: python cb_advisor.py <申番> <アドバイス|FB>
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("usage: python cb_advisor.py <申込受付番号> <アドバイス|FB>")
        sys.exit(1)
    number, mode = sys.argv[1], sys.argv[2]
    from sf_client import get_sf

    sf = get_sf()
    case = fetch_case(sf, number)
    if not case["found"]:
        print("案件が見つかりません:", number)
        sys.exit(1)
    print(f"--- {case['account_name']} / tasks={case['task_total']} ---")
    print(generate(case, mode))
