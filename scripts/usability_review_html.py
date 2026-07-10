from __future__ import annotations

import base64
import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from scripts.usability_review_common import (
    ALLOWED_FEEDBACK_FLAGS,
    FLAG_LABELS,
    RATING_DIMENSIONS,
    RATING_LABELS,
    STATUS_LABELS,
)

PAYLOAD_PATTERN = re.compile(r'const REVIEW_DATA_B64 = "([A-Za-z0-9+/=]+)";')

RATING_HELP = {
    "understandability": "전문 용어 없이 첫 독해에서 이해할 수 있는지 평가합니다.",
    "actionability": "출발 여부나 재확인 행동을 결정하는 데 도움이 되는지 평가합니다.",
    "uncertainty_clarity": "확인된 정보와 미확인 정보가 분명히 구분되는지 평가합니다.",
    "accessibility_relevance": "길찾기보다 교통약자 접근성 정보가 중심인지 평가합니다.",
    "brevity": "핵심 정보는 유지하면서 불필요하게 길지 않은지 평가합니다.",
}


class ReviewEntryLike(Protocol):
    case_name: str
    category: str
    persona: str
    review_focus: list[str]
    question: str
    status: str
    user_message: str
    response_sha256: str


def build_review_html_payload(
    entries: Sequence[ReviewEntryLike],
    *,
    mode: str,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "version": 1,
        "mode": mode,
        "generated_at": generated_at.isoformat(),
        "dimensions": [
            {
                "key": key,
                "label": RATING_LABELS[key],
                "help": RATING_HELP[key],
            }
            for key in RATING_DIMENSIONS
        ],
        "flags": [
            {"key": key, "label": FLAG_LABELS[key]}
            for key in ALLOWED_FEEDBACK_FLAGS
        ],
        "cases": [
            {
                "case_name": entry.case_name,
                "category": entry.category,
                "persona": entry.persona,
                "review_focus": entry.review_focus,
                "question": entry.question,
                "status": entry.status,
                "status_label": STATUS_LABELS.get(entry.status, entry.status),
                "user_message": entry.user_message,
                "response_sha256": entry.response_sha256,
            }
            for entry in entries
        ],
    }


def encode_review_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_review_payload(encoded: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


def extract_review_payload(html: str) -> dict[str, Any]:
    match = PAYLOAD_PATTERN.search(html)
    if not match:
        raise ValueError("review payload is missing from HTML")
    return decode_review_payload(match.group(1))


def render_review_html(
    entries: Sequence[ReviewEntryLike],
    *,
    mode: str,
    generated_at: datetime,
) -> str:
    payload = build_review_html_payload(
        entries,
        mode=mode,
        generated_at=generated_at,
    )
    return HTML_TEMPLATE.replace("__REVIEW_DATA_B64__", encode_review_payload(payload))


HTML_TEMPLATE = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; script-src 'unsafe-inline';
                 style-src 'unsafe-inline'; img-src data:; connect-src 'none';
                 object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>Barrier-Free Mobility MCP 사용성 리뷰</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f5f6;
      --surface: #ffffff;
      --surface-muted: #eef2f3;
      --ink: #172129;
      --muted: #5a6872;
      --line: #cbd4d9;
      --accent: #087f5b;
      --accent-dark: #056044;
      --focus: #0067c5;
      --warning: #8a5a00;
      --danger: #b42318;
      --shadow: 0 8px 24px rgb(23 33 41 / 8%);
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      font-size: 16px;
    }

    * {
      box-sizing: border-box;
      letter-spacing: 0;
    }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.6;
    }

    button,
    input,
    select,
    textarea {
      font: inherit;
    }

    button,
    select,
    input[type="file"],
    textarea,
    .text-input {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--ink);
    }

    button:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible {
      outline: 3px solid color-mix(in srgb, var(--focus) 35%, transparent);
      outline-offset: 2px;
    }

    .skip-link {
      position: fixed;
      top: 0;
      left: 1rem;
      z-index: 10;
      padding: 0.7rem 1rem;
      transform: translateY(-130%);
      background: var(--ink);
      color: #ffffff;
    }

    .skip-link:focus {
      transform: translateY(0);
    }

    .topbar {
      border-bottom: 4px solid var(--accent);
      background: var(--surface);
    }

    .topbar-inner,
    .shell {
      width: min(1120px, calc(100% - 2rem));
      margin: 0 auto;
    }

    .topbar-inner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      min-height: 72px;
    }

    .brand h1 {
      margin: 0;
      font-size: 1.25rem;
      line-height: 1.3;
    }

    .brand p {
      margin: 0.15rem 0 0;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .mode-meta {
      color: var(--muted);
      font-size: 0.9rem;
      text-align: right;
    }

    .shell {
      padding: 1.5rem 0 7rem;
    }

    .review-meta {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(240px, 360px);
      gap: 1.5rem;
      align-items: end;
      padding: 1.25rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }

    .progress-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 0.4rem;
    }

    progress {
      width: 100%;
      height: 0.8rem;
      accent-color: var(--accent);
    }

    .field-label {
      display: block;
      margin-bottom: 0.35rem;
      font-weight: 700;
    }

    .text-input,
    select,
    input[type="file"] {
      width: 100%;
      min-height: 44px;
      padding: 0.55rem 0.7rem;
    }

    .privacy-note {
      margin: 0.5rem 0 0;
      color: var(--muted);
      font-size: 0.85rem;
    }

    .case-header {
      margin-top: 1.5rem;
      padding: 1.25rem;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: var(--surface-muted);
    }

    .case-kicker {
      margin: 0 0 0.2rem;
      color: var(--accent-dark);
      font-size: 0.85rem;
      font-weight: 700;
    }

    .case-header h2 {
      margin: 0;
      font-size: 1.35rem;
    }

    .case-status {
      margin: 0.35rem 0 0;
      color: var(--muted);
    }

    .context-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px;
      margin-top: 1px;
      background: var(--line);
    }

    .context-section {
      min-width: 0;
      padding: 1.25rem;
      background: var(--surface);
    }

    .context-section h3,
    .answer-section h3,
    .evaluation-section h3 {
      margin: 0 0 0.7rem;
      font-size: 1.05rem;
    }

    .context-section p,
    .context-section ul {
      margin: 0;
    }

    .context-section ul {
      padding-left: 1.25rem;
    }

    .answer-section {
      padding: 1.5rem;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }

    .answer-heading-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-top: 1.25rem;
    }

    .answer-heading-row h3 {
      margin: 0;
    }

    .view-switch {
      display: inline-flex;
      gap: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }

    .view-switch button {
      min-height: 38px;
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
      font-weight: 600;
    }

    .view-switch button:last-child {
      border-right: 0;
    }

    .view-switch button[aria-pressed="true"] {
      background: var(--ink);
      color: #ffffff;
    }

    .question {
      margin: 0 0 1.25rem;
      padding: 0.9rem 1rem;
      border-left: 4px solid var(--warning);
      background: #fff8e7;
      font-weight: 700;
    }

    .answer {
      min-height: 180px;
      margin: 0.75rem 0 0;
      padding: 1.2rem;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
      border-left: 4px solid var(--accent);
      background: #f8fbfa;
      font-family: inherit;
    }

    .answer[hidden] {
      display: none;
    }

    .rendered-answer {
      white-space: normal;
    }

    .rendered-answer > :first-child {
      margin-top: 0;
    }

    .rendered-answer > :last-child {
      margin-bottom: 0;
    }

    .rendered-answer h4 {
      margin: 1.5rem 0 0.6rem;
      font-size: 1rem;
    }

    .rendered-answer p,
    .rendered-answer ul,
    .rendered-answer blockquote {
      margin: 0.55rem 0;
    }

    .rendered-answer ul {
      padding-left: 1.3rem;
    }

    .rendered-answer .verdict {
      display: inline-block;
      padding: 0.35rem 0.65rem;
      border-left: 4px solid var(--warning);
      background: #fff8e7;
      font-size: 1.05rem;
    }

    .rendered-answer blockquote {
      padding: 0.75rem 1rem;
      border-left: 4px solid var(--warning);
      background: #fff8e7;
    }

    .table-wrap {
      max-width: 100%;
      margin: 0.75rem 0;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
    }

    .rendered-answer table {
      width: 100%;
      min-width: 620px;
      border-collapse: collapse;
      background: var(--surface);
    }

    .rendered-answer th,
    .rendered-answer td {
      padding: 0.7rem;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }

    .rendered-answer th:last-child,
    .rendered-answer td:last-child {
      border-right: 0;
    }

    .rendered-answer tbody tr:last-child td {
      border-bottom: 0;
    }

    .rendered-answer th {
      background: var(--surface-muted);
      font-weight: 700;
    }

    .evaluation-section {
      padding: 1.5rem;
      background: var(--surface);
    }

    .rating-list {
      display: grid;
      gap: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }

    .rating-field {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(320px, 1fr);
      gap: 1rem;
      align-items: center;
      min-width: 0;
      margin: 0;
      padding: 1rem;
      border: 0;
      border-bottom: 1px solid var(--line);
    }

    .rating-field:last-child {
      border-bottom: 0;
    }

    .rating-field legend {
      display: contents;
    }

    .rating-copy strong,
    .rating-copy small {
      display: block;
    }

    .rating-copy small {
      margin-top: 0.2rem;
      color: var(--muted);
    }

    .score-options {
      display: grid;
      grid-template-columns: repeat(5, minmax(48px, 1fr));
      gap: 0.35rem;
    }

    .score-option {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.3rem;
      min-height: 44px;
      padding: 0.3rem;
      border: 1px solid var(--line);
      border-radius: 6px;
      cursor: pointer;
    }

    .score-option:has(input:checked) {
      border-color: var(--accent);
      background: #e6f4ef;
      font-weight: 700;
    }

    .score-option input {
      width: 1.05rem;
      height: 1.05rem;
      accent-color: var(--accent);
    }

    .flags-section {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.55rem 1rem;
      margin-top: 1.5rem;
      padding: 1rem;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .flags-section legend {
      padding: 0 0.35rem;
      font-weight: 700;
    }

    .flag-option {
      display: flex;
      gap: 0.6rem;
      align-items: flex-start;
      min-height: 44px;
      padding: 0.55rem;
    }

    .flag-option input {
      flex: 0 0 auto;
      width: 1.15rem;
      height: 1.15rem;
      margin-top: 0.2rem;
      accent-color: var(--danger);
    }

    .comment-section {
      margin-top: 1.5rem;
    }

    textarea {
      width: 100%;
      min-height: 120px;
      padding: 0.75rem;
      resize: vertical;
    }

    .comment-meta {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      color: var(--muted);
      font-size: 0.85rem;
    }

    .toolbar {
      position: sticky;
      bottom: 0;
      z-index: 5;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 0.75rem;
      width: min(1120px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 0.9rem;
      border: 1px solid var(--line);
      border-bottom: 0;
      border-radius: 8px 8px 0 0;
      background: rgb(255 255 255 / 96%);
      box-shadow: 0 -6px 20px rgb(23 33 41 / 10%);
    }

    .button-group {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    button {
      min-height: 44px;
      padding: 0.55rem 0.9rem;
      cursor: pointer;
      font-weight: 700;
    }

    button:hover:not(:disabled) {
      border-color: var(--accent);
    }

    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    button.primary:hover:not(:disabled) {
      background: var(--accent-dark);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.5;
    }

    .status-message {
      width: min(1120px, calc(100% - 2rem));
      min-height: 1.7rem;
      margin: 0.5rem auto;
      color: var(--accent-dark);
      font-weight: 700;
    }

    .status-message.error {
      color: var(--danger);
    }

    @media (max-width: 760px) {
      .topbar-inner,
      .review-meta,
      .context-grid,
      .rating-field {
        display: block;
      }

      .topbar-inner {
        padding: 0.85rem 0;
      }

      .mode-meta {
        margin-top: 0.35rem;
        text-align: left;
      }

      .review-meta > div + div,
      .score-options {
        margin-top: 1rem;
      }

      .answer-heading-row {
        display: block;
      }

      .view-switch {
        margin-top: 0.6rem;
      }

      .context-grid {
        background: transparent;
      }

      .context-section {
        border-bottom: 1px solid var(--line);
      }

      .flags-section {
        grid-template-columns: 1fr;
      }

      .toolbar,
      .button-group {
        width: 100%;
      }

      .toolbar button {
        flex: 1 1 140px;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      *,
      *::before,
      *::after {
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#review-main">평가 영역으로 바로가기</a>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <h1>Barrier-Free Mobility MCP 사용성 리뷰</h1>
        <p>질문별 답변을 읽고 일반 사용자 관점에서 평가합니다.</p>
      </div>
      <div class="mode-meta" id="mode-meta"></div>
    </div>
  </header>

  <main class="shell" id="review-main">
    <section class="review-meta" aria-labelledby="progress-heading">
      <div>
        <div class="progress-row">
          <strong id="progress-heading">평가 진행률</strong>
          <span id="progress-text"></span>
        </div>
        <progress id="review-progress" value="0" max="1"></progress>
        <p class="privacy-note">
          이름, 이메일, 장애 진단명, 개인 이동 기록은 입력하지 마세요.
        </p>
      </div>
      <div>
        <label class="field-label" for="reviewer-id">리뷰어 식별자(선택)</label>
        <input class="text-input" id="reviewer-id" maxlength="64"
               autocomplete="off" placeholder="예: reviewer-01">
        <label class="field-label" for="case-jump" style="margin-top: 0.8rem">
          평가할 질문
        </label>
        <select id="case-jump"></select>
      </div>
    </section>

    <article aria-labelledby="case-title">
      <header class="case-header">
        <p class="case-kicker" id="case-position"></p>
        <h2 id="case-title" tabindex="-1"></h2>
        <p class="case-status" id="case-status"></p>
      </header>

      <div class="context-grid">
        <section class="context-section" aria-labelledby="persona-heading">
          <h3 id="persona-heading">사용자 상황</h3>
          <p id="persona"></p>
        </section>
        <section class="context-section" aria-labelledby="focus-heading">
          <h3 id="focus-heading">검토할 내용</h3>
          <ul id="review-focus"></ul>
        </section>
      </div>

      <section class="answer-section" aria-labelledby="answer-heading">
        <h3>사용자 질문</h3>
        <p class="question" id="question"></p>
        <div class="answer-heading-row">
          <h3 id="answer-heading">MCP 답변</h3>
          <div class="view-switch" role="group" aria-label="답변 표시 방식">
            <button id="formatted-view" type="button" aria-pressed="true">
              읽기 좋은 보기
            </button>
            <button id="raw-view" type="button" aria-pressed="false">MCP 원문</button>
          </div>
        </div>
        <div class="answer rendered-answer" id="answer"></div>
        <pre class="answer" id="answer-raw" hidden></pre>
      </section>

      <section class="evaluation-section" aria-labelledby="evaluation-heading">
        <h3 id="evaluation-heading">답변 평가</h3>
        <div class="rating-list" id="rating-list"></div>
        <fieldset class="flags-section" id="flags-section">
          <legend>문제가 있으면 선택하세요</legend>
        </fieldset>
        <div class="comment-section">
          <label class="field-label" for="comment">자유 의견(선택)</label>
          <textarea id="comment" maxlength="1000"
                    placeholder="구체적인 개선 방향만 작성하세요."></textarea>
          <div class="comment-meta">
            <span>개인 식별 정보는 작성하지 마세요.</span>
            <span id="comment-count">0 / 1000</span>
          </div>
        </div>
      </section>
    </article>
  </main>

  <p class="status-message" id="status-message" role="status" aria-live="polite"></p>
  <nav class="toolbar" aria-label="리뷰 작업">
    <div class="button-group">
      <button id="previous-case" type="button">이전 질문</button>
      <button id="next-case" type="button">다음 질문</button>
    </div>
    <div class="button-group">
      <label>
        <span class="field-label">저장한 JSON 불러오기</span>
        <input id="import-file" type="file" accept="application/json,.json">
      </label>
      <button id="export-draft" type="button">초안 JSON 내보내기</button>
      <button class="primary" id="export-complete" type="button">
        완료 JSON 내보내기
      </button>
    </div>
  </nav>

  <script>
    "use strict";

    const REVIEW_DATA_B64 = "__REVIEW_DATA_B64__";
    const MAX_IMPORT_BYTES = 1048576;
    const data = decodePayload(REVIEW_DATA_B64);
    const allowedFlags = new Set(data.flags.map((item) => item.key));
    const dimensionKeys = data.dimensions.map((item) => item.key);
    const reviews = data.cases.map((item) => ({
      case_name: item.case_name,
      response_sha256: item.response_sha256,
      ratings: Object.fromEntries(dimensionKeys.map((key) => [key, null])),
      flags: [],
      comment: ""
    }));
    let currentIndex = 0;
    let answerViewMode = "formatted";

    const elements = {
      modeMeta: document.getElementById("mode-meta"),
      progress: document.getElementById("review-progress"),
      progressText: document.getElementById("progress-text"),
      reviewerId: document.getElementById("reviewer-id"),
      caseJump: document.getElementById("case-jump"),
      casePosition: document.getElementById("case-position"),
      caseTitle: document.getElementById("case-title"),
      caseStatus: document.getElementById("case-status"),
      persona: document.getElementById("persona"),
      reviewFocus: document.getElementById("review-focus"),
      question: document.getElementById("question"),
      answer: document.getElementById("answer"),
      answerRaw: document.getElementById("answer-raw"),
      formattedView: document.getElementById("formatted-view"),
      rawView: document.getElementById("raw-view"),
      ratingList: document.getElementById("rating-list"),
      flagsSection: document.getElementById("flags-section"),
      comment: document.getElementById("comment"),
      commentCount: document.getElementById("comment-count"),
      previous: document.getElementById("previous-case"),
      next: document.getElementById("next-case"),
      importFile: document.getElementById("import-file"),
      exportDraft: document.getElementById("export-draft"),
      exportComplete: document.getElementById("export-complete"),
      status: document.getElementById("status-message")
    };

    function decodePayload(encoded) {
      const binary = atob(encoded);
      const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
      return JSON.parse(new TextDecoder().decode(bytes));
    }

    function createElement(tag, className, text) {
      const element = document.createElement(tag);
      if (className) {
        element.className = className;
      }
      if (text !== undefined) {
        element.textContent = text;
      }
      return element;
    }

    function splitTableRow(line) {
      const value = line.trim().replace(/^\|/, "").replace(/\|$/, "");
      const cells = [];
      let current = "";
      for (let index = 0; index < value.length; index += 1) {
        const char = value[index];
        if (char === "\\" && value[index + 1] === "|") {
          current += "|";
          index += 1;
        } else if (char === "|") {
          cells.push(current.trim());
          current = "";
        } else {
          current += char;
        }
      }
      cells.push(current.trim());
      return cells;
    }

    function isTableSeparator(line) {
      const cells = splitTableRow(line);
      return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
    }

    function isMarkdownControlLine(lines, index) {
      const line = lines[index] || "";
      if (!line.trim()) {
        return true;
      }
      if (line.startsWith("### ") || line.startsWith("- ") || line.startsWith("> ")) {
        return true;
      }
      if (line.startsWith("**") && line.endsWith("**")) {
        return true;
      }
      return (
        line.trim().startsWith("|") &&
        index + 1 < lines.length &&
        isTableSeparator(lines[index + 1])
      );
    }

    function appendMarkdownTable(container, lines, startIndex) {
      const header = splitTableRow(lines[startIndex]);
      const wrapper = createElement("div", "table-wrap");
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      header.forEach((cell) => headerRow.append(createElement("th", "", cell)));
      thead.append(headerRow);
      table.append(thead);

      const tbody = document.createElement("tbody");
      let index = startIndex + 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        const row = document.createElement("tr");
        splitTableRow(lines[index]).forEach((cell) => {
          row.append(createElement("td", "", cell));
        });
        tbody.append(row);
        index += 1;
      }
      table.append(tbody);
      wrapper.append(table);
      container.append(wrapper);
      return index;
    }

    function renderMarkdownMessage(message, container) {
      const lines = message.split(/\r?\n/);
      container.replaceChildren();
      let index = 0;
      while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
          index += 1;
          continue;
        }
        if (
          line.trim().startsWith("|") &&
          index + 1 < lines.length &&
          isTableSeparator(lines[index + 1])
        ) {
          index = appendMarkdownTable(container, lines, index);
          continue;
        }
        if (line.startsWith("### ")) {
          container.append(createElement("h4", "", line.slice(4).trim()));
          index += 1;
          continue;
        }
        if (line.startsWith("- ")) {
          const list = document.createElement("ul");
          while (index < lines.length && lines[index].startsWith("- ")) {
            list.append(createElement("li", "", lines[index].slice(2).trim()));
            index += 1;
          }
          container.append(list);
          continue;
        }
        if (line.startsWith("> ")) {
          container.append(createElement("blockquote", "", line.slice(2).trim()));
          index += 1;
          continue;
        }
        if (line.startsWith("**") && line.endsWith("**")) {
          const paragraph = createElement("p", "verdict");
          paragraph.append(createElement("strong", "", line.slice(2, -2)));
          container.append(paragraph);
          index += 1;
          continue;
        }

        const paragraphLines = [line.trim()];
        index += 1;
        while (index < lines.length && !isMarkdownControlLine(lines, index)) {
          paragraphLines.push(lines[index].trim());
          index += 1;
        }
        container.append(createElement("p", "", paragraphLines.join(" ")));
      }
    }

    function updateAnswerView() {
      const formatted = answerViewMode === "formatted";
      elements.answer.hidden = !formatted;
      elements.answerRaw.hidden = formatted;
      elements.formattedView.setAttribute("aria-pressed", String(formatted));
      elements.rawView.setAttribute("aria-pressed", String(!formatted));
    }

    function isComplete(review) {
      return dimensionKeys.every((key) => Number.isInteger(review.ratings[key]));
    }

    function completedCount() {
      return reviews.filter(isComplete).length;
    }

    function renderProgress() {
      const complete = completedCount();
      elements.progress.max = reviews.length;
      elements.progress.value = complete;
      elements.progressText.textContent = `${complete} / ${reviews.length} 완료`;
      elements.exportComplete.disabled = complete !== reviews.length;

      Array.from(elements.caseJump.options).forEach((option, index) => {
        const prefix = isComplete(reviews[index]) ? "[완료]" : "[미완료]";
        option.textContent = `${prefix} ${index + 1}. ${data.cases[index].case_name}`;
      });
    }

    function renderRatings(review, reviewCase) {
      elements.ratingList.replaceChildren();
      data.dimensions.forEach((dimension) => {
        const fieldset = createElement("fieldset", "rating-field");
        const legend = document.createElement("legend");
        const copy = createElement("span", "rating-copy");
        const label = createElement("strong", "", dimension.label);
        const help = createElement("small", "", dimension.help);
        copy.append(label, help);
        legend.append(copy);
        fieldset.append(legend);

        const options = createElement("div", "score-options");
        options.setAttribute("aria-label", `${dimension.label} 점수`);
        for (let score = 1; score <= 5; score += 1) {
          const option = createElement("label", "score-option");
          const input = document.createElement("input");
          input.type = "radio";
          input.name = `rating-${reviewCase.case_name}-${dimension.key}`;
          input.value = String(score);
          input.checked = review.ratings[dimension.key] === score;
          input.addEventListener("change", () => {
            review.ratings[dimension.key] = score;
            renderProgress();
          });
          option.append(input, document.createTextNode(String(score)));
          options.append(option);
        }
        fieldset.append(options);
        elements.ratingList.append(fieldset);
      });
    }

    function renderFlags(review) {
      elements.flagsSection.querySelectorAll(".flag-option").forEach((item) => {
        item.remove();
      });
      data.flags.forEach((flag) => {
        const option = createElement("label", "flag-option");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = flag.key;
        input.checked = review.flags.includes(flag.key);
        input.addEventListener("change", () => {
          if (input.checked && !review.flags.includes(flag.key)) {
            review.flags.push(flag.key);
          } else if (!input.checked) {
            review.flags = review.flags.filter((item) => item !== flag.key);
          }
        });
        option.append(input, document.createTextNode(flag.label));
        elements.flagsSection.append(option);
      });
    }

    function renderCase({ focusTitle = false } = {}) {
      const reviewCase = data.cases[currentIndex];
      const review = reviews[currentIndex];
      elements.casePosition.textContent = `질문 ${currentIndex + 1} / ${data.cases.length}`;
      elements.caseTitle.textContent = reviewCase.case_name;
      elements.caseStatus.textContent = `답변 생성 상태: ${reviewCase.status_label}`;
      elements.persona.textContent = reviewCase.persona;
      elements.reviewFocus.replaceChildren(
        ...reviewCase.review_focus.map((focus) => createElement("li", "", focus))
      );
      elements.question.textContent = reviewCase.question;
      renderMarkdownMessage(reviewCase.user_message, elements.answer);
      elements.answerRaw.textContent = reviewCase.user_message;
      updateAnswerView();
      renderRatings(review, reviewCase);
      renderFlags(review);
      elements.comment.value = review.comment;
      elements.commentCount.textContent = `${review.comment.length} / 1000`;
      elements.caseJump.value = String(currentIndex);
      elements.previous.disabled = currentIndex === 0;
      elements.next.disabled = currentIndex === data.cases.length - 1;
      renderProgress();
      if (focusTitle) {
        elements.caseTitle.focus();
      }
    }

    function setCurrentCase(index, { focusTitle = true } = {}) {
      if (!Number.isInteger(index) || index < 0 || index >= data.cases.length) {
        return;
      }
      currentIndex = index;
      renderCase({ focusTitle });
      window.scrollTo({ top: 0, behavior: "auto" });
    }

    function buildFeedback(completed) {
      return {
        version: 1,
        reviewer_id: elements.reviewerId.value.trim(),
        reviewed_at: completed ? new Date().toISOString() : null,
        mode: data.mode,
        cases: reviews.map((review) => ({
          case_name: review.case_name,
          response_sha256: review.response_sha256,
          ratings: { ...review.ratings },
          flags: [...review.flags],
          comment: review.comment
        }))
      };
    }

    function downloadJson(payload, filename) {
      const blob = new Blob(
        [JSON.stringify(payload, null, 2)],
        { type: "application/json;charset=utf-8" }
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    }

    function setStatus(message, error = false) {
      elements.status.textContent = message;
      elements.status.classList.toggle("error", error);
    }

    function validateImportedFeedback(payload) {
      if (!payload || payload.version !== 1 || payload.mode !== data.mode) {
        throw new Error("현재 리뷰와 mode 또는 version이 다릅니다.");
      }
      if (!Array.isArray(payload.cases) || payload.cases.length !== reviews.length) {
        throw new Error("리뷰 케이스 수가 다릅니다.");
      }
      const imported = new Map(payload.cases.map((item) => [item.case_name, item]));
      return reviews.map((review) => {
        const item = imported.get(review.case_name);
        if (!item || item.response_sha256 !== review.response_sha256) {
          throw new Error(`${review.case_name} 답변 버전이 다릅니다.`);
        }
        const ratings = {};
        dimensionKeys.forEach((key) => {
          const value = item.ratings ? item.ratings[key] : null;
          if (value !== null && (!Number.isInteger(value) || value < 1 || value > 5)) {
            throw new Error(`${review.case_name} 점수 범위가 올바르지 않습니다.`);
          }
          ratings[key] = value;
        });
        const flags = Array.isArray(item.flags) ? [...new Set(item.flags)] : [];
        if (flags.some((flag) => !allowedFlags.has(flag))) {
          throw new Error(`${review.case_name}에 지원하지 않는 문제 표시가 있습니다.`);
        }
        const comment = typeof item.comment === "string" ? item.comment : "";
        if (comment.length > 1000) {
          throw new Error(`${review.case_name} 자유 의견이 1,000자를 초과했습니다.`);
        }
        return {
          case_name: review.case_name,
          response_sha256: review.response_sha256,
          ratings,
          flags,
          comment
        };
      });
    }

    function initialize() {
      elements.modeMeta.textContent = `${data.mode} mode · ${data.cases.length}개 질문`;
      data.cases.forEach((item, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        elements.caseJump.append(option);
      });

      elements.caseJump.addEventListener("change", () => {
        setCurrentCase(Number(elements.caseJump.value));
      });
      elements.previous.addEventListener("click", () => {
        setCurrentCase(currentIndex - 1);
      });
      elements.next.addEventListener("click", () => {
        setCurrentCase(currentIndex + 1);
      });
      elements.formattedView.addEventListener("click", () => {
        answerViewMode = "formatted";
        updateAnswerView();
      });
      elements.rawView.addEventListener("click", () => {
        answerViewMode = "raw";
        updateAnswerView();
      });
      elements.comment.addEventListener("input", () => {
        reviews[currentIndex].comment = elements.comment.value;
        elements.commentCount.textContent = `${elements.comment.value.length} / 1000`;
      });
      elements.exportDraft.addEventListener("click", () => {
        downloadJson(
          buildFeedback(false),
          `usability-feedback-${data.mode}-draft.json`
        );
        setStatus("초안 JSON을 내보냈습니다.");
      });
      elements.exportComplete.addEventListener("click", () => {
        const firstIncomplete = reviews.findIndex((review) => !isComplete(review));
        if (firstIncomplete !== -1) {
          setCurrentCase(firstIncomplete);
          setStatus("모든 평가 항목에 1~5점을 입력해 주세요.", true);
          return;
        }
        downloadJson(
          buildFeedback(true),
          `usability-feedback-${data.mode}-completed.json`
        );
        setStatus("완료 JSON을 내보냈습니다.");
      });
      elements.importFile.addEventListener("change", async () => {
        const file = elements.importFile.files[0];
        if (!file) {
          return;
        }
        try {
          if (file.size > MAX_IMPORT_BYTES) {
            throw new Error("1MB 이하 JSON 파일만 불러올 수 있습니다.");
          }
          const payload = JSON.parse(await file.text());
          const importedReviews = validateImportedFeedback(payload);
          importedReviews.forEach((review, index) => {
            reviews[index] = review;
          });
          elements.reviewerId.value = String(payload.reviewer_id || "").slice(0, 64);
          renderCase();
          setStatus("저장한 리뷰를 불러왔습니다.");
        } catch (error) {
          setStatus(error instanceof Error ? error.message : "JSON을 불러오지 못했습니다.", true);
        } finally {
          elements.importFile.value = "";
        }
      });

      renderCase();
    }

    initialize();
  </script>
</body>
</html>
'''
