"""
ログイン画面に表示するミニゲーム集。

GAMES に3種類のゲームを定義し、JST日付に応じて日替わりローテーションする。
- mogura  : モグラ叩き（10秒・3x3グリッド・クリック/タップ）
- reaction: リアクションタイム（色が変わったらクリック、5回平均ms）
- calc    : 1分間計算（簡単な暗算を連続解答、正解数で勝負）

各ゲームは完全にクライアントサイドで完結（components.html 用の単一HTML）。
ベストスコアは localStorage に保存される。
"""

from datetime import datetime, timezone, timedelta

_JST = timezone(timedelta(hours=9))


# ============================================================
# 共通スタイル（カードラッパ）
# ============================================================
_BASE_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Hiragino Sans', 'Yu Gothic', sans-serif;
  color: #fff;
  background: transparent;
  user-select: none;
  -webkit-user-select: none;
}
.game-card {
  background: rgba(255,255,255,0.08);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 18px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.4);
  padding: 16px 20px 18px;
  margin: 0;
  animation: cardIn 0.6s cubic-bezier(0.2,0.9,0.3,1.2) both;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
.game-title {
  text-align: center;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
  background: linear-gradient(90deg, #fff, #d1c4e9, #b39ddb);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.stats {
  display: flex;
  justify-content: space-around;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.85);
  margin-bottom: 12px;
  padding: 6px 8px;
  background: rgba(0,0,0,0.18);
  border-radius: 10px;
  text-align: center;
}
.stats .val { color: #fff; font-weight: 700; font-size: 0.95rem; }
.btn {
  display: block;
  width: 100%;
  margin-top: 12px;
  padding: 10px;
  background: linear-gradient(135deg, #7e57c2, #5e35b1 60%, #4527a0);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(81,45,168,0.45);
  transition: all 0.2s;
}
.btn:hover {
  transform: translateY(-2px);
  filter: brightness(1.12);
  box-shadow: 0 12px 26px rgba(81,45,168,0.6);
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.result {
  text-align: center;
  margin-top: 10px;
  font-size: 0.95rem;
  font-weight: 700;
  min-height: 1.4em;
}
.result.win { color: #ffd54f; text-shadow: 0 0 10px rgba(255,213,79,0.5); }
.result.bad { color: rgba(255,255,255,0.7); }
.result.best { color: #ff80ab; text-shadow: 0 0 10px rgba(255,128,171,0.6); animation: pulse 1.2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
.tag {
  display: inline-block;
  font-size: 0.7rem;
  padding: 2px 8px;
  background: rgba(179,157,219,0.25);
  border: 1px solid rgba(179,157,219,0.5);
  border-radius: 999px;
  color: #d1c4e9;
  margin-left: 6px;
  vertical-align: middle;
}
"""


# ============================================================
# B: モグラ叩き
# ============================================================
_GAME_MOGURA_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
__BASE_STYLE__
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.hole {
  position: relative;
  aspect-ratio: 1 / 1;
  background: radial-gradient(ellipse at center, #2a1745 0%, #110724 80%);
  border-radius: 50%;
  overflow: hidden;
  cursor: pointer;
  box-shadow: inset 0 6px 12px rgba(0,0,0,0.6), 0 2px 6px rgba(0,0,0,0.3);
  transition: transform 0.08s ease;
}
.hole:active { transform: scale(0.96); }
.mole {
  position: absolute; left: 10%; right: 10%; bottom: -100%; height: 80%;
  background: linear-gradient(180deg, #c08457 0%, #8b5a2b 70%, #6b4423 100%);
  border-radius: 50% 50% 45% 45% / 60% 60% 40% 40%;
  display: flex; flex-direction: column; align-items: center; justify-content: flex-start;
  padding-top: 18%;
  transition: bottom 0.22s cubic-bezier(0.3, 1.4, 0.5, 1);
  box-shadow: inset 0 -10px 16px rgba(0,0,0,0.35);
}
.mole.up { bottom: 0; }
.mole.hit { background: linear-gradient(180deg, #e91e63 0%, #ad1457 100%); }
.mole .face {
  width: 70%; height: 60%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; position: relative;
}
.mole .eyes { display: flex; gap: 18%; width: 70%; margin-bottom: 8%; }
.mole .eye {
  width: 28%; aspect-ratio: 1/1; background: #fff;
  border-radius: 50%; position: relative;
}
.mole .eye::after {
  content: ""; position: absolute; top: 30%; left: 30%; width: 40%; height: 40%;
  background: #1a1a2e; border-radius: 50%;
}
.mole .nose { width: 22%; aspect-ratio: 1/0.7; background: #2a1010; border-radius: 50%; }
.mole.hit::after {
  content: "💥"; position: absolute; top: 30%; left: 50%;
  transform: translate(-50%,-50%); font-size: 1.8rem; animation: hitPop 0.4s ease;
}
@keyframes hitPop {
  0% { transform: translate(-50%,-50%) scale(0.5); opacity: 1; }
  100% { transform: translate(-50%,-90%) scale(1.8); opacity: 0; }
}
</style></head><body>
<div class="game-card">
  <div class="game-title">🐹 モグラ叩き <span class="tag">今日のゲーム</span></div>
  <div class="stats">
    <div>SCORE<div class="val" id="score">0</div></div>
    <div>TIME<div class="val" id="time">10</div></div>
    <div>BEST<div class="val" id="best">0</div></div>
  </div>
  <div class="grid" id="grid"></div>
  <button class="btn" id="startBtn">▶ スタート</button>
  <div class="result" id="result">クリック / タップで叩く！</div>
</div>
<script>
(function(){
  const HOLES = 9, DURATION = 10, POP_MIN = 600, POP_MAX = 1100;
  const grid = document.getElementById('grid');
  const scoreEl = document.getElementById('score');
  const timeEl = document.getElementById('time');
  const bestEl = document.getElementById('best');
  const startBtn = document.getElementById('startBtn');
  const resultEl = document.getElementById('result');
  const holes = [];
  for (let i = 0; i < HOLES; i++) {
    const hole = document.createElement('div'); hole.className = 'hole';
    const mole = document.createElement('div'); mole.className = 'mole';
    mole.innerHTML = '<div class="face"><div class="eyes"><div class="eye"></div><div class="eye"></div></div><div class="nose"></div></div>';
    hole.appendChild(mole); grid.appendChild(hole);
    holes.push({hole, mole, alive: false});
    const hit = (e) => {
      e.preventDefault();
      if (!running) return;
      const h = holes[i];
      if (h.alive && !h.mole.classList.contains('hit')) {
        h.mole.classList.add('hit'); score++; scoreEl.textContent = score;
        setTimeout(() => { h.mole.classList.remove('up','hit'); h.alive = false; }, 180);
      }
    };
    hole.addEventListener('click', hit);
    hole.addEventListener('touchstart', hit, {passive:false});
  }
  let running = false, score = 0, timeLeft = DURATION;
  let timerId = null, popTimerId = null;
  let best = parseInt(localStorage.getItem('cs_mole_best') || '0', 10);
  bestEl.textContent = best;
  function popRandom() {
    if (!running) return;
    const idle = holes.filter(h => !h.alive);
    if (idle.length > 0) {
      const target = idle[Math.floor(Math.random() * idle.length)];
      target.alive = true; target.mole.classList.add('up');
      const stayMs = 700 + Math.random() * 700;
      setTimeout(() => {
        if (target.alive) { target.mole.classList.remove('up'); target.alive = false; }
      }, stayMs);
    }
    popTimerId = setTimeout(popRandom, POP_MIN + Math.random() * (POP_MAX - POP_MIN));
  }
  function start() {
    running = true; score = 0; timeLeft = DURATION;
    scoreEl.textContent = '0'; timeEl.textContent = DURATION;
    resultEl.textContent = '叩け！叩け！叩け！'; resultEl.className = 'result';
    startBtn.disabled = true; startBtn.textContent = 'プレイ中...';
    timerId = setInterval(() => { timeLeft--; timeEl.textContent = timeLeft; if (timeLeft <= 0) end(); }, 1000);
    popRandom();
    setTimeout(() => { if (running) popRandom(); }, 200);
  }
  function end() {
    running = false; clearInterval(timerId); clearTimeout(popTimerId);
    holes.forEach(h => { h.mole.classList.remove('up','hit'); h.alive = false; });
    startBtn.disabled = false; startBtn.textContent = '🔄 もう一度';
    if (score > best) {
      best = score; localStorage.setItem('cs_mole_best', String(best));
      bestEl.textContent = best;
      resultEl.textContent = '🎉 自己ベスト更新！ ' + score + '点';
      resultEl.className = 'result best';
    } else if (score >= 15) {
      resultEl.textContent = '🔥 ' + score + '点 — 良いスコア！'; resultEl.className = 'result win';
    } else if (score >= 8) {
      resultEl.textContent = score + '点 — まずまず'; resultEl.className = 'result';
    } else {
      resultEl.textContent = score + '点 — もう少し！'; resultEl.className = 'result bad';
    }
  }
  startBtn.addEventListener('click', start);
})();
</script></body></html>
"""


# ============================================================
# A: リアクションタイム
# ============================================================
_GAME_REACTION_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
__BASE_STYLE__
.target {
  height: 200px;
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.3rem; font-weight: 700;
  cursor: pointer;
  transition: background 0.05s ease;
  box-shadow: inset 0 0 30px rgba(0,0,0,0.3);
  letter-spacing: 0.05em;
  text-align: center;
  padding: 16px;
}
.target.idle  { background: linear-gradient(135deg, #3a2755, #1a1a2e); color: rgba(255,255,255,0.6); }
.target.wait  { background: linear-gradient(135deg, #d32f2f, #7f0000); color: #fff; }
.target.go    { background: linear-gradient(135deg, #43a047, #1b5e20); color: #fff; font-size: 1.6rem; animation: goFlash 0.4s ease; }
.target.early { background: linear-gradient(135deg, #f9a825, #ef6c00); color: #fff; }
@keyframes goFlash { from { transform: scale(1.05); } to { transform: scale(1); } }
.round-dots { display: flex; gap: 6px; justify-content: center; margin-top: 10px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: rgba(255,255,255,0.15); }
.dot.done { background: linear-gradient(135deg, #b39ddb, #7e57c2); box-shadow: 0 0 8px rgba(179,157,219,0.5); }
.dot.current { background: #fff; }
</style></head><body>
<div class="game-card">
  <div class="game-title">⚡ リアクションタイム <span class="tag">今日のゲーム</span></div>
  <div class="stats">
    <div>ラウンド<div class="val" id="round">0/5</div></div>
    <div>前回<div class="val" id="last">— ms</div></div>
    <div>ベスト<div class="val" id="best">— ms</div></div>
  </div>
  <div class="target idle" id="target">▶ クリックでスタート</div>
  <div class="round-dots" id="dots"></div>
  <div class="result" id="result">緑になった瞬間にクリック！</div>
</div>
<script>
(function(){
  const ROUNDS = 5;
  const target = document.getElementById('target');
  const roundEl = document.getElementById('round');
  const lastEl = document.getElementById('last');
  const bestEl = document.getElementById('best');
  const dotsEl = document.getElementById('dots');
  const resultEl = document.getElementById('result');

  let state = 'idle';
  let roundIdx = 0;
  let times = [];
  let waitStart = 0;
  let timerId = null;

  let best = parseInt(localStorage.getItem('cs_reaction_best') || '0', 10);
  bestEl.textContent = best > 0 ? (best + ' ms') : '— ms';

  function renderDots() {
    dotsEl.innerHTML = '';
    for (let i = 0; i < ROUNDS; i++) {
      const d = document.createElement('div');
      d.className = 'dot' + (i < times.length ? ' done' : (i === roundIdx ? ' current' : ''));
      dotsEl.appendChild(d);
    }
  }

  function startRound() {
    roundEl.textContent = (roundIdx + 1) + '/' + ROUNDS;
    renderDots();
    state = 'wait';
    target.className = 'target wait';
    target.textContent = '...待て...';
    resultEl.textContent = '緑になったらクリック！';
    resultEl.className = 'result';
    const delay = 1200 + Math.random() * 2300;
    timerId = setTimeout(() => {
      state = 'go';
      waitStart = performance.now();
      target.className = 'target go';
      target.textContent = 'NOW!';
    }, delay);
  }

  function finishGame() {
    const avg = Math.round(times.reduce((a,b)=>a+b,0) / times.length);
    state = 'idle';
    target.className = 'target idle';
    target.textContent = '🔄 もう一度プレイ';
    renderDots();
    lastEl.textContent = avg + ' ms';
    if (best === 0 || avg < best) {
      best = avg;
      localStorage.setItem('cs_reaction_best', String(best));
      bestEl.textContent = best + ' ms';
      resultEl.textContent = '🎉 自己ベスト更新！ 平均 ' + avg + 'ms';
      resultEl.className = 'result best';
    } else if (avg < 280) {
      resultEl.textContent = '🔥 平均 ' + avg + 'ms — 反応神！';
      resultEl.className = 'result win';
    } else if (avg < 400) {
      resultEl.textContent = '平均 ' + avg + 'ms — まずまず';
      resultEl.className = 'result';
    } else {
      resultEl.textContent = '平均 ' + avg + 'ms — 朝はゆっくり…';
      resultEl.className = 'result bad';
    }
  }

  function onClick() {
    if (state === 'idle') {
      roundIdx = 0; times = [];
      lastEl.textContent = '— ms';
      startRound();
    } else if (state === 'wait') {
      clearTimeout(timerId);
      state = 'idle';
      target.className = 'target early';
      target.textContent = '⚠ フライング！もう一度クリック';
      resultEl.textContent = 'フライングはダメ。次は緑を待って。';
      resultEl.className = 'result bad';
      times = []; roundIdx = 0;
      renderDots();
    } else if (state === 'go') {
      const ms = Math.round(performance.now() - waitStart);
      times.push(ms);
      roundIdx++;
      lastEl.textContent = ms + ' ms';
      if (roundIdx >= ROUNDS) {
        finishGame();
      } else {
        target.className = 'target idle';
        target.textContent = ms + ' ms — 次へ進む（クリック）';
        state = 'next';
      }
    } else if (state === 'next') {
      startRound();
    }
  }

  target.addEventListener('click', onClick);
  target.addEventListener('touchstart', (e) => { e.preventDefault(); onClick(); }, {passive:false});
  renderDots();
})();
</script></body></html>
"""


# ============================================================
# C: 1分間計算
# ============================================================
_GAME_CALC_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
__BASE_STYLE__
.quiz {
  background: rgba(0,0,0,0.25);
  border-radius: 14px;
  padding: 22px 18px;
  text-align: center;
  margin-bottom: 10px;
  min-height: 110px;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  position: relative;
  overflow: hidden;
}
.quiz .question {
  font-size: 2.3rem; font-weight: 800;
  letter-spacing: 0.05em;
  background: linear-gradient(90deg, #fff, #d1c4e9);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.quiz .answer-input {
  width: 80%; max-width: 200px;
  margin-top: 10px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.92);
  color: #1a1a2e;
  border: 1px solid rgba(255,255,255,0.4);
  border-radius: 10px;
  font-size: 1.4rem; font-weight: 700;
  text-align: center;
  outline: none;
}
.quiz .answer-input:focus {
  border-color: #b39ddb;
  box-shadow: 0 0 0 4px rgba(179,157,219,0.25);
}
.quiz.flash-ok { animation: flashOk 0.3s ease; }
.quiz.flash-ng { animation: flashNg 0.3s ease; }
@keyframes flashOk { 0%,100% {background: rgba(0,0,0,0.25);} 50% {background: rgba(76,175,80,0.35);} }
@keyframes flashNg { 0%,100% {background: rgba(0,0,0,0.25);} 50% {background: rgba(244,67,54,0.35);} }
.progress {
  height: 6px; background: rgba(255,255,255,0.1); border-radius: 999px; overflow: hidden;
  margin-top: 8px;
}
.progress-bar {
  height: 100%; width: 100%;
  background: linear-gradient(90deg, #43a047, #ffd54f, #e53935);
  transition: width 1s linear;
}
.hint {
  text-align: center;
  font-size: 0.75rem;
  color: rgba(255,255,255,0.55);
  margin-top: 4px;
}
</style></head><body>
<div class="game-card">
  <div class="game-title">🧮 1分間計算 <span class="tag">今日のゲーム</span></div>
  <div class="stats">
    <div>正解<div class="val" id="score">0</div></div>
    <div>残り<div class="val" id="time">60</div>s</div>
    <div>ベスト<div class="val" id="best">0</div></div>
  </div>
  <div class="quiz" id="quiz">
    <div class="question" id="question">▶ スタート</div>
  </div>
  <div class="progress"><div class="progress-bar" id="progressBar"></div></div>
  <button class="btn" id="startBtn">▶ スタート</button>
  <div class="result hint" id="result">入力して Enter キーで回答</div>
</div>
<script>
(function(){
  const DURATION = 60;
  const quizEl = document.getElementById('quiz');
  const questionEl = document.getElementById('question');
  const scoreEl = document.getElementById('score');
  const timeEl = document.getElementById('time');
  const bestEl = document.getElementById('best');
  const startBtn = document.getElementById('startBtn');
  const resultEl = document.getElementById('result');
  const progressBar = document.getElementById('progressBar');

  let running = false;
  let score = 0;
  let timeLeft = DURATION;
  let currentAnswer = 0;
  let timerId = null;
  let answerInput = null;

  let best = parseInt(localStorage.getItem('cs_calc_best') || '0', 10);
  bestEl.textContent = best;

  function makeQuestion() {
    // 演算子をランダム選択（加算30%・減算30%・乗算25%・小さな割算15%）
    const r = Math.random();
    let a, b, op, ans;
    if (r < 0.30) {
      a = 5 + Math.floor(Math.random() * 70);
      b = 5 + Math.floor(Math.random() * 70);
      op = '+'; ans = a + b;
    } else if (r < 0.60) {
      a = 20 + Math.floor(Math.random() * 80);
      b = 5 + Math.floor(Math.random() * (a - 4));
      op = '−'; ans = a - b;
    } else if (r < 0.85) {
      a = 2 + Math.floor(Math.random() * 11);
      b = 2 + Math.floor(Math.random() * 11);
      op = '×'; ans = a * b;
    } else {
      b = 2 + Math.floor(Math.random() * 8);
      ans = 2 + Math.floor(Math.random() * 12);
      a = b * ans;
      op = '÷';
    }
    currentAnswer = ans;
    questionEl.innerHTML = '';
    const q = document.createElement('div');
    q.className = 'question';
    q.textContent = a + ' ' + op + ' ' + b + ' = ?';
    questionEl.appendChild(q);

    answerInput = document.createElement('input');
    answerInput.type = 'tel';
    answerInput.inputMode = 'numeric';
    answerInput.pattern = '[0-9-]*';
    answerInput.className = 'answer-input';
    answerInput.autocomplete = 'off';
    quizEl.appendChild(answerInput);
    answerInput.focus();

    answerInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitAnswer();
      }
    });
    answerInput.addEventListener('input', () => {
      // 桁数が回答に到達したら即判定（オプション）
      const v = answerInput.value;
      if (v && parseInt(v, 10) === currentAnswer) {
        submitAnswer();
      }
    });
  }

  function submitAnswer() {
    if (!running || !answerInput) return;
    const v = parseInt(answerInput.value, 10);
    if (!isNaN(v) && v === currentAnswer) {
      score++; scoreEl.textContent = score;
      quizEl.classList.remove('flash-ng');
      quizEl.classList.add('flash-ok');
      setTimeout(() => quizEl.classList.remove('flash-ok'), 300);
      cleanInput();
      makeQuestion();
    } else {
      quizEl.classList.remove('flash-ok');
      quizEl.classList.add('flash-ng');
      setTimeout(() => quizEl.classList.remove('flash-ng'), 300);
      answerInput.value = '';
      answerInput.focus();
    }
  }

  function cleanInput() {
    if (answerInput) { answerInput.remove(); answerInput = null; }
  }

  function start() {
    running = true;
    score = 0; timeLeft = DURATION;
    scoreEl.textContent = '0'; timeEl.textContent = DURATION;
    progressBar.style.transition = 'none';
    progressBar.style.width = '100%';
    setTimeout(() => {
      progressBar.style.transition = 'width 1s linear';
    }, 50);
    resultEl.textContent = '頑張れ！正解で次の問題';
    resultEl.className = 'result hint';
    startBtn.disabled = true;
    startBtn.textContent = 'プレイ中...';
    cleanInput();
    makeQuestion();
    timerId = setInterval(() => {
      timeLeft--;
      timeEl.textContent = timeLeft;
      progressBar.style.width = ((timeLeft / DURATION) * 100) + '%';
      if (timeLeft <= 0) end();
    }, 1000);
  }

  function end() {
    running = false;
    clearInterval(timerId);
    cleanInput();
    questionEl.innerHTML = '<div class="question">⏰ 終了</div>';
    startBtn.disabled = false;
    startBtn.textContent = '🔄 もう一度';
    progressBar.style.width = '0%';
    if (score > best) {
      best = score; localStorage.setItem('cs_calc_best', String(best));
      bestEl.textContent = best;
      resultEl.textContent = '🎉 自己ベスト更新！ ' + score + '問正解';
      resultEl.className = 'result best';
    } else if (score >= 25) {
      resultEl.textContent = '🔥 ' + score + '問 — 計算マスター！'; resultEl.className = 'result win';
    } else if (score >= 15) {
      resultEl.textContent = score + '問 — 良いペース'; resultEl.className = 'result';
    } else {
      resultEl.textContent = score + '問 — 朝の頭の体操に'; resultEl.className = 'result bad';
    }
  }

  startBtn.addEventListener('click', start);
  // クイズエリアをクリックでフォーカス復帰
  quizEl.addEventListener('click', () => { if (answerInput) answerInput.focus(); });
})();
</script></body></html>
"""


# ============================================================
# ローテーション
# ============================================================
_GAMES = [
    {"key": "reaction", "html": _GAME_REACTION_HTML, "height": 470, "label": "⚡ リアクションタイム"},
    {"key": "mogura",   "html": _GAME_MOGURA_HTML,   "height": 510, "label": "🐹 モグラ叩き"},
    {"key": "calc",     "html": _GAME_CALC_HTML,     "height": 500, "label": "🧮 1分間計算"},
]


def pick_today_game() -> dict:
    """JST日付の通算日 % 3 で日替わりに1ゲーム選択。"""
    today = datetime.now(_JST).date()
    idx = today.toordinal() % len(_GAMES)
    game = _GAMES[idx]
    html = game["html"].replace("__BASE_STYLE__", _BASE_STYLE)
    return {
        "key": game["key"],
        "html": html,
        "height": game["height"],
        "label": game["label"],
    }
