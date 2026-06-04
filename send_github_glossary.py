"""
GitHub基本用語集 日替わり配信スクリプト（GitHub Actions用）

用語1〜9を日替わりで1つ選び、指定のChatworkルームへ毎日10:00に送信する。
選択は日付ベース（その年の通算日）で決まるため、配信が一日抜けても
重複や巻き戻りは起きず、淡々と日替わりで巡回する。
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import requests

CHATWORK_API_TOKEN = os.environ.get("CHATWORK_API_TOKEN", "")
CHATWORK_API_URL = "https://api.chatwork.com/v2"
JST = timezone(timedelta(hours=9))

# 用語集の送信先ルームID（用語集専用の新規ルーム）
ROOM_ID = os.environ.get("GLOSSARY_ROOM_ID", "REPLACE_WITH_ROOM_ID")

# --- 用語集本文（1〜9） ---
GLOSSARY = [
    # 1. clone
    "[info][title]GitHub用語 ①clone（クローン）[/title]"
    "■何をする？\n"
    "GitHubに保存されているプロジェクトの内容を、あなたのパソコンにコピーする操作です。"
    "このコピーを使って、自分のパソコンでコードを編集できるようになります。\n\n"
    "■なぜ必要？\n"
    "初めてプロジェクトに参加するときは、まずリモート（GitHub）にあるコードをコピーして"
    "手元に持ってくる必要があります。それが「クローン」です。\n\n"
    "■例え\n"
    "先生が黒板に書いた内容を、あなたのノートに書き写す作業が「クローン」です。\n\n"
    "■具体例\n"
    "git clone https://github.com/username/project-name.git[/info]",

    # 2. branch
    "[info][title]GitHub用語 ②Branch（ブランチ）[/title]"
    "■何をする？\n"
    "メインのコードとは別の「コピー」を作成して、その中で新しい機能を開発したり修正を行います。"
    "このコピーを「ブランチ」と呼びます。\n\n"
    "■なぜ必要？\n"
    "メインのコードを直接変更すると他の人に影響が出る可能性があります。"
    "ブランチを使うことで、独立した作業環境を作れます。\n\n"
    "■例え\n"
    "配られたプリントのコピーを取り、そのコピーに答えを書くイメージ。本物（メインブランチ）はそのまま。\n\n"
    "■具体例\n"
    "git branch feature/add-login-page\n"
    "git checkout feature/add-login-page[/info]",

    # 3. commit
    "[info][title]GitHub用語 ③Commit（コミット）[/title]"
    "■何をする？\n"
    "コードを保存する操作です。ただの保存ではなく、何をどう変えたかの履歴を一緒に記録します。"
    "後で「いつ・誰が・どんな変更をしたか」を確認できます。\n\n"
    "■なぜ必要？\n"
    "問題が起きたとき過去の状態に戻せます。また、誰がどの部分を変更したのかをチームで共有できます。\n\n"
    "■例え\n"
    "作文に「今日はここまで」と日付を書いて保存しておくイメージ。\n\n"
    "■具体例\n"
    'git commit -m "Add login form to LoginPage component"[/info]',

    # 4. push
    "[info][title]GitHub用語 ④Push（プッシュ）[/title]"
    "■何をする？\n"
    "自分のパソコンで保存した変更（コミット）を、GitHubに送る操作です。"
    "これをしないと、チームメンバーがあなたの変更を見られません。\n\n"
    "■なぜ必要？\n"
    "プッシュすることで、GitHubのリポジトリにあなたの作業内容が反映され、他の人と共有できます。\n\n"
    "■例え\n"
    "ノートに書いた宿題を先生に提出するイメージ。\n\n"
    "■具体例\n"
    "git push origin feature/add-login-page[/info]",

    # 5. pull request
    "[info][title]GitHub用語 ⑤Pull Request（プルリクエスト）[/title]"
    "■何をする？\n"
    "自分が作業したブランチの内容をメイン（main）に統合してもらうためのお願いを出します。"
    "他のメンバーが内容を確認し、問題がなければ統合されます。\n\n"
    "■なぜ必要？\n"
    "確認せずに統合するとバグが混ざる可能性があります。プルリクは確認のための「提出書類」のようなものです。\n\n"
    "■例え\n"
    "宿題を出すとき「この答えで正しいか先生に確認してもらう」感じ。\n\n"
    "■具体例\n"
    "GitHub上で、作業ブランチをメインに統合するプルリクエストを作成。[/info]",

    # 6. merge
    "[info][title]GitHub用語 ⑥Merge（マージ）[/title]"
    "■何をする？\n"
    "プルリクエストが承認された後、作業ブランチの変更をメインブランチに統合します。\n\n"
    "■なぜ必要？\n"
    "チーム全員が同じ最新のコードを使えるようにするため。\n\n"
    "■例え\n"
    "宿題の答えが確認されて、クラス全員に配られるイメージ。\n\n"
    "■具体例\n"
    "git checkout main\n"
    "git merge feature/add-login-page[/info]",

    # 7. pull
    "[info][title]GitHub用語 ⑦Pull（プル）[/title]"
    "■何をする？\n"
    "他のメンバーがGitHubのメインブランチに追加した変更を、自分のパソコンに反映します。\n\n"
    "■なぜ必要？\n"
    "メンバー全員が同じ最新のコードで作業できるようにするため。\n\n"
    "■例え\n"
    "クラスメートが教えてくれた新しい情報を、自分のノートに書き写す感じ。\n\n"
    "■具体例\n"
    "git pull origin main[/info]",

    # 8. conflict
    "[info][title]GitHub用語 ⑧Conflict（コンフリクト）[/title]"
    "■何をする？\n"
    "競合が発生した場合、どの変更を採用するかを手動で決めて修正します。\n\n"
    "■なぜ必要？\n"
    "複数人が同じファイルを変更していると、どちらの変更を採用するかをGitが判断できないため。\n\n"
    "■例え\n"
    "同じノートに違う人が違う答えを書いてしまった状態。それをまとめて正しいものにする感じ。\n\n"
    "■具体例\n"
    "競合箇所を修正し、再度コミットする。[/info]",

    # 9. issue
    "[info][title]GitHub用語 ⑨Issue（イシュー）[/title]"
    "■何をする？\n"
    "バグや機能追加など、やるべきタスクをGitHub上で管理します。\n\n"
    "■なぜ必要？\n"
    "チーム全員がやるべき作業を把握しやすくするため。\n\n"
    "■例え\n"
    "学校の「今日の宿題リスト」を全員で共有する感じ。\n\n"
    "■具体例\n"
    "「ログイン画面でエラーメッセージが出ない」というバグをIssueとして記録。[/info]",
]


def pick_index(now: datetime) -> int:
    """その年の通算日から日替わりインデックス(0〜8)を決める。"""
    day_of_year = now.timetuple().tm_yday
    return (day_of_year - 1) % len(GLOSSARY)


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
        print("ERROR: GLOSSARY_ROOM_ID not set")
        sys.exit(1)

    now = datetime.now(JST)
    idx = pick_index(now)
    body = GLOSSARY[idx]

    print(f"--- {now.strftime('%Y/%m/%d')} 用語 No.{idx + 1} ---")
    print(body)
    print("--- Sending ---")
    send_chatwork(body, ROOM_ID)
    print("Done")


if __name__ == "__main__":
    main()
