/**
 * 代コンローダー GASスクリプト
 *
 * 設置先: スプレッドシート "1iNtEakg4U4C3p7uQlVcJIzojnUd8uW5Ykl8swQRQD5U"
 *        拡張機能 → Apps Script にコンテナバインドで配置
 *
 * トリガー: onEditLoader を「編集時」のインストーラブルトリガーとして登録
 *          （K列の貼り付け/入力/削除で発火、時間トリガー不要）
 *
 * 使用シート:
 *   - 代コンデータ連携ローダー貼り付け用 (書き込み対象。以下「貼り付け用」)
 *   - SO新設プリティーダービー用 (読取専用。sync_report.py が自動書込。以下「ダービー用」)
 *   - 代コンマスタ (読取専用)
 *
 * 仕様:
 *   1. 貼り付け用 K列が空 → 同行の J〜AU列 をクリア
 *   2. 貼り付け用 Q/R列 が空 → 現在日付/時刻を自動入力
 *   3. 貼り付け用 K列 を キーに ダービー用 D列 を検索
 *      一致行の ダービー用 T〜AS (26列) を 貼り付け用 V〜AU (26列) へ位置コピー
 *      ※AU列のみ時刻文字列("16:00:00.000Z"等)を Date化して h:mm 表示に
 *   4. S列: `yyyy/MM/dd HH:MM\n対応方針：{マスタB}` + O列テキスト(---で囲い)
 *   5. 代コンマスタ適用 (貼り付け用 N列 をキーに マスタ A列 検索):
 *      - マスタD → W列   (保護対象、以下の W値 のとき変更禁止)
 *      - マスタE → X列   (常時上書き)
 *      - マスタC → Y列   (常時上書き)
 *      - マスタF → AT列  (保護対象)
 *      - マスタG → AU列  (保護対象、時刻Date化)
 *      保護条件 (W列の値):
 *        キャンセル依頼 / 折返し希望(開通後/自社OP) / 折返し希望（開通前） / キャンセル確認待ち
 *   6. Z/AB/AD/AF/AH/AJ/AL/AN/AP/AR 列 に マスタC を「最後に値のある位置の次」に追記
 *      次の列 (AA/AC/AE/AG/AI/AK/AM/AO/AQ/AS) に S列値
 *      重複(同一 "対応方針：" キー)は追記しない
 *      ※保護条件 true でも 実行される
 */

function onEditLoader(e) {
  if (!e || !e.range) return;

  const sheet = e.range.getSheet();
  if (sheet.getName() !== "代コンデータ連携ローダー貼り付け用") return;

  const col = e.range.getColumn();
  const lastCol = e.range.getLastColumn();
  if (col > 11 || lastCol < 11) return;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const source = ss.getSheetByName("SO新設プリティーダービー用");
  const masterSheet = ss.getSheetByName("代コンマスタ");

  const now = new Date();
  const dateStr = Utilities.formatDate(now, "Asia/Tokyo", "yyyy/MM/dd");
  const timeStr = Utilities.formatDate(now, "Asia/Tokyo", "HH:mm");

  // ===== 一括取得 =====
  const startRow = e.range.getRow();
  const numRows = e.range.getNumRows();

  const range = sheet.getRange(startRow, 1, numRows, 47);
  const data = range.getValues();

  const srcData = source.getDataRange().getValues();
  const masterData = masterSheet.getDataRange().getValues();

  // ===== index化 =====
  const srcIndex = {};
  srcData.slice(1).forEach(r => {
    const key = String(r[3] || "").trim();
    if (key) srcIndex[key] = r;
  });

  const master = {};
  masterData.slice(1).forEach(r => {
    if (r[0]) {
      master[String(r[0]).trim()] = {
        b: r[1],
        c: r[2],
        d: r[3],
        e: r[4],
        f: r[5],
        g: r[6]
      };
    }
  });

  const normalize = v => {
    const text = String(v || "").replace(/\r?\n/g, "");
    const parts = text.split("対応方針：");
    return parts.length > 1 ? parts[1].trim() : "";
  };

  // 時刻文字列("16:00:00.000Z"等)をDate化。Date/空/非時刻はそのまま
  const parseTime = (v) => {
    if (v instanceof Date) return v;
    const s = String(v || "").trim();
    if (!s) return "";
    const m = s.match(/^(\d{1,2}):(\d{2})/);
    if (!m) return v;
    const d = new Date(1899, 11, 30);
    d.setHours(parseInt(m[1], 10), parseInt(m[2], 10), 0, 0);
    return d;
  };

  const PROTECT = [
    "キャンセル依頼",
    "折返し希望(開通後/自社OP)",
    "折返し希望（開通前）",
    "キャンセル確認待ち"
  ];

  // ===== メモリ処理 =====
  for (let i = 0; i < data.length; i++) {

    const row = data[i];
    const receiptNo = String(row[10] || "").trim(); // K
    const status    = String(row[13] || "").trim(); // N

    // K空 → J〜AUクリア
    if (!receiptNo) {
      for (let c = 9; c <= 46; c++) row[c] = "";
      continue;
    }

    // Q/R 自動入力
    if (!row[16]) row[16] = dateStr;
    if (!row[17]) row[17] = timeStr;

    // ダービー連携 (T〜AS → V〜AU)
    const src = srcIndex[receiptNo];
    if (src) {
      for (let c = 19; c <= 44; c++) {
        const v = (src[c] !== undefined && src[c] !== null) ? src[c] : "";
        row[c + 2] = (c + 2 === 46) ? parseTime(v) : v;  // AU列は時刻Date化
      }
    } else {
      for (let c = 21; c <= 46; c++) row[c] = "";
    }

    // マスタ取得
    const m = master[status];
    const mB = m ? (m.b || "") : "";
    const mC = m ? (m.c || "") : "";
    const mD = m ? (m.d || "") : "";
    const mE = m ? (m.e || "") : "";
    const mF = m ? (m.f || "") : "";
    const mG = m ? (m.g || "") : "";

    // S列
    const oText = String(row[14] || "").trim();
    let sText = `${dateStr} ${timeStr}\n対応方針：${mB}`;
    if (oText) sText += `\n---\n${oText}\n---`;
    row[18] = sText;

    // 上書き制御
    const wCurrent = String(row[22] || "").trim();
    const protect = PROTECT.includes(wCurrent);

    row[23] = mE;  // X: 常時
    row[24] = mC;  // Y: 常時

    if (!protect) {
      row[22] = mD;  // W
      row[45] = mF;  // AT
      if (mG) {
        const t = new Date(1899, 11, 30);
        const [h, min] = String(mG).split(":").map(Number);
        t.setHours(h || 0, min || 0, 0, 0);
        row[46] = t;  // AU
      } else {
        row[46] = "";
      }
    }

    // フェーズ③: Z/AB/AD/... に マスタC を末尾追記、次列にS列値
    if (m) {
      const reasonCols = [25,27,29,31,33,35,37,39,41,43];
      const sKey = normalize(sText);
      const exists = reasonCols.some(col => normalize(row[col + 1]) === sKey);

      if (!exists && sKey) {
        let lastFilledIdx = -1;
        for (let k = 0; k < reasonCols.length; k++) {
          if (String(row[reasonCols[k]] || "").trim()) {
            lastFilledIdx = k;
          }
        }
        const idx = lastFilledIdx + 1;
        if (idx < reasonCols.length) {
          const col = reasonCols[idx];
          row[col] = mC;
          row[col + 1] = sText;
        }
      }
    }
  }

  // ===== 一括反映 =====
  range.setValues(data);
  sheet.getRange(startRow, 47, numRows).setNumberFormat("h:mm");
}
