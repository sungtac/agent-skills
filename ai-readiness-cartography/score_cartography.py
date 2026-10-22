#!/usr/bin/env python3
"""AI Readiness Cartography — static diagnostic scorer for file-based
multi-agent orchestration harnesses (MultiAgent Orchestrator convention:
tasks/<task>/{task.md,context.md,log.md,workers/<role>/{brief.md,result.md}}).

Read-only with respect to the scanned --target: never edits, moves, or deletes
files under it. Prints a Markdown report to stdout by default; --output writes
the report to the given path (may be inside --target, e.g. an artifacts/
folder) — this is the report file itself, not a modification of scanned
source files, and will overwrite an existing file at that path.
"""
import argparse
import glob
import os
import re
import sys

KNOWN_WORKERS = {"claude-main", "codex-main", "codex-critic", "gemini"}
REQUIRED_TASK_HEADERS = ["## 메타", "## Goal", "## Constraints", "## Acceptance Criteria", "## Worker Plan"]
REQUIRED_BRIEF_LINES = [
    "요청 범위만 최소로",
    "외과수술식 수정",
    "사용자 대화 채널 없음",
]
CONTEXT_CHAR_LIMIT = 1500
BRIEF_CHAR_LIMIT = 1200


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def find_tasks(root):
    return sorted(glob.glob(os.path.join(root, "tasks", "*")))


def score_worker_routing(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        task_md = read(os.path.join(t, "task.md"))
        if task_md is None:
            continue
        checked += 1
        roles = set(re.findall(r"worker:\s*(\S+)", task_md)) | set(re.findall(r"role:\s*(\S+)", task_md))
        roles = {r.strip() for r in roles if r.strip() and not r.strip().startswith("#")}
        unknown = roles - KNOWN_WORKERS
        if unknown:
            notes.append(f"{os.path.basename(t)}: 미등록 워커명 {sorted(unknown)}")
        else:
            ok += 1
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def score_task_doc_consistency(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        task_md_path = os.path.join(t, "task.md")
        task_md = read(task_md_path)
        if task_md is None:
            continue
        checked += 1
        missing = [h for h in REQUIRED_TASK_HEADERS if h not in task_md]
        ctx = read(os.path.join(t, "context.md"))
        over_limit = ctx is not None and len(ctx) > CONTEXT_CHAR_LIMIT
        if missing:
            notes.append(f"{os.path.basename(t)}: task.md 헤더 누락 {missing}")
        if over_limit:
            notes.append(f"{os.path.basename(t)}: context.md {len(ctx)}자 (제한 {CONTEXT_CHAR_LIMIT}자 초과)")
        if not missing and not over_limit:
            ok += 1
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def score_brief_reusability(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        for brief_path in glob.glob(os.path.join(t, "workers", "*", "brief.md")):
            brief = read(brief_path)
            if brief is None:
                continue
            checked += 1
            rel = os.path.relpath(brief_path, root)
            missing = [line for line in REQUIRED_BRIEF_LINES if line not in brief]
            over_limit = len(brief) > BRIEF_CHAR_LIMIT
            if missing:
                notes.append(f"{rel}: 고정 규약 문구 누락 {missing}")
            if over_limit:
                notes.append(f"{rel}: {len(brief)}자 (제한 {BRIEF_CHAR_LIMIT}자 초과)")
            if not missing and not over_limit:
                ok += 1
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def extract_approved_roles(task_md):
    # workers_approved: 블록만 슬라이싱 — planned_workers/주석/본문의 우연한
    # "worker: X" 문자열이 승인으로 오탐되는 것 방지(codex-critic·gemini 교차확인 발견)
    match = re.search(r"workers_approved:.*?(?=\nplanned_workers:|\n```)", task_md, re.DOTALL)
    if not match:
        return set()
    return set(re.findall(r"worker:\s*(\S+)", match.group(0)))


def score_approval_gate(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        task_md = read(os.path.join(t, "task.md")) or ""
        approved_roles = extract_approved_roles(task_md)
        for result_path in glob.glob(os.path.join(t, "workers", "*", "result.md")):
            role = os.path.basename(os.path.dirname(result_path))
            checked += 1
            rel = os.path.relpath(result_path, root)
            # claude-main도 approval-policy.md상 명시적 승인 필요 — 예외 없음
            if role in approved_roles:
                ok += 1
            else:
                notes.append(f"{rel}: result.md 존재하나 task.md workers_approved에 '{role}' 승인 기록 없음")
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def score_verification_loop(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        task_md = read(os.path.join(t, "task.md")) or ""
        status_match = re.search(r"status:\s*(\S+)", task_md)
        status = status_match.group(1) if status_match else ""
        if status != "done":
            continue
        checked += 1
        log_md = read(os.path.join(t, "log.md")) or ""
        if "[VERIFICATION]" in log_md:
            ok += 1
        else:
            notes.append(f"{os.path.basename(t)}: status=done인데 log.md에 [VERIFICATION] 기록 없음")
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def score_doc_freshness(root, tasks):
    shared_dir = os.path.join(root, "_shared")
    checked, ok = 0, 0
    notes = []
    if not os.path.isdir(shared_dir):
        return None, notes, 0
    for md_path in glob.glob(os.path.join(shared_dir, "*.md")):
        content = read(md_path) or ""
        # backtick으로 감싼 상대경로 참조를 찾아 실존 여부 확인
        refs = re.findall(r"`(_shared/[\w./-]+|_templates/[\w./-]+)`", content)
        for ref in set(refs):
            checked += 1
            if os.path.exists(os.path.join(root, ref)):
                ok += 1
            else:
                notes.append(f"{os.path.relpath(md_path, root)}: 참조 경로 '{ref}' 실존하지 않음")
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


def score_rabbit_hole_management(root, tasks):
    checked, ok = 0, 0
    notes = []
    for t in tasks:
        log_md = read(os.path.join(t, "log.md")) or ""
        for line in log_md.splitlines():
            if "[DISCOVERY]" not in line:
                continue
            checked += 1
            if "session=" in line:
                ok += 1
            else:
                notes.append(f"{os.path.basename(t)}: [DISCOVERY] 라인에 session= 필드 누락 — {line.strip()[:80]}")
    pct = (ok / checked * 100) if checked else None
    return pct, notes, checked


CATEGORIES = [
    ("워커 라우팅 명확성", score_worker_routing),
    ("태스크 문서 일관성", score_task_doc_consistency),
    ("브리프 재사용성", score_brief_reusability),
    ("승인 게이트 준수", score_approval_gate),
    ("검증 루프 준수", score_verification_loop),
    ("문서 최신성", score_doc_freshness),
    ("토끼굴 관리", score_rabbit_hole_management),
]


def build_report(root):
    import datetime

    tasks = find_tasks(root)
    results = []
    scored = []
    for name, fn in CATEGORIES:
        pct, notes, checked = fn(root, tasks)
        if pct is not None:
            scored.append(pct)
        results.append((name, pct, notes, checked))
    overall = (sum(scored) / len(scored)) if scored else None

    lines = []
    lines.append("# AI Readiness Cartography 진단 리포트")
    lines.append("")
    lines.append(f"- 생성 시각: {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 대상: `{root}`")
    lines.append(f"- 스캔한 task 폴더 수: {len(tasks)}")
    if overall is None:
        lines.append("- **종합 점수: N/A (검사 가능한 항목 없음 — 대상 구조를 확인하세요)**")
    else:
        lines.append(f"- **종합 점수: {overall:.0f} / 100** (검사항목 0건인 카테고리는 N/A로 집계 제외)")
    lines.append("")
    lines.append("| 카테고리 | 점수 | 검사 항목 수 |")
    lines.append("|---|---|---|")
    for name, pct, notes, checked in results:
        score_str = "N/A" if pct is None else f"{pct:.0f}"
        lines.append(f"| {name} | {score_str} | {checked} |")
    lines.append("")

    lines.append("## 우선순위 액션")
    lines.append("")
    actionable = sorted(results, key=lambda r: r[1] if r[1] is not None else 101)
    action_count = 0
    for name, pct, notes, checked in actionable:
        if not notes:
            continue
        score_str = "N/A" if pct is None else f"{pct:.0f}점"
        lines.append(f"### {name} ({score_str})")
        for n in notes[:10]:
            lines.append(f"- {n}")
        if len(notes) > 10:
            lines.append(f"- ... 외 {len(notes) - 10}건")
        lines.append("")
        action_count += 1
    if action_count == 0:
        if scored and all(p == 100 for p in scored):
            lines.append("(발견된 이슈 없음 — 검사 가능한 전 카테고리 100점)")
        else:
            lines.append("(발견된 이슈 없음 — 단, 검사 가능한 항목이 없어 대부분 N/A. "
                          "대상 구조를 확인하세요)")
        lines.append("")

    lines.append("## 카테고리 정의")
    lines.append("")
    lines.append("- **워커 라우팅 명확성**: task.md의 worker/role 표기가 등록된 4워커"
                  "(claude-main/codex-main/codex-critic/gemini) 중 하나인가")
    lines.append("- **태스크 문서 일관성**: task.md 필수 헤더 존재, context.md 글자수 제한(1500자) 준수")
    lines.append("- **브리프 재사용성**: brief.md 고정 규약 문구 포함, 1200자 제한 준수")
    lines.append("- **승인 게이트 준수**: result.md가 있는 워커는 task.md workers_approved에 기록돼 있는가")
    lines.append("- **검증 루프 준수**: status=done인 작업은 log.md에 [VERIFICATION] 기록이 있는가")
    lines.append("- **문서 최신성**: _shared/*.md가 참조하는 상대경로가 실제로 존재하는가")
    lines.append("- **토끼굴 관리**: log.md의 [DISCOVERY] 라인이 session= 필드를 포함하는가"
                  "(orchestrator-rules.md §4.3 형식)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.getcwd(),
                         help="진단 대상 루트 경로 (기본: 현재 디렉터리). tasks/ 폴더가 있는 경로여야 함.")
    parser.add_argument("--output", default=None, help="리포트를 저장할 파일 경로 (기본: stdout)")
    args = parser.parse_args()

    root = os.path.abspath(args.target)
    if not os.path.isdir(os.path.join(root, "tasks")):
        print(f"경고: '{root}/tasks' 디렉터리가 없습니다 — MultiAgent 하네스 구조가 아닐 수 있습니다.",
              file=sys.stderr)

    report = build_report(root)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"리포트 저장: {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
