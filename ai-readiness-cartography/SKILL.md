---
name: ai-readiness-cartography
description: Static, read-only diagnostic scorer for file-based MultiAgent Orchestrator harnesses (tasks/<task>/{task.md,context.md,log.md,workers/}). Scores 7 categories (worker routing clarity, task doc consistency, brief reusability, approval gate compliance, verification loop compliance, doc freshness, rabbit-hole management) and produces a Markdown report with priority actions. Use when the user says "카토그래피 돌려줘/실행해줘/검사해줘", "AI 레디니스 점검해줘", "하네스 진단해줘/헬스체크", "diagnose/cartography the harness", or asks how AI-agent-friendly the multiagent tasks/ structure is.
---

# AI Readiness Cartography

MultiAgent Orchestrator 하네스(`tasks/<task>/` 파일 기반 상태 관리 구조)가 에이전트
입장에서 얼마나 길을 잃지 않고 작업할 수 있는 상태인지 정적으로 진단하는 스킬.
읽기 전용 — 대상 코드를 수정하지 않는다.

## 언제 쓰나

- 사용자가 "카토그래피 돌려줘", "하네스 AI 레디니스 점검해줘" 등으로 요청할 때
- MultiAgent 하네스(`_shared/`, `_templates/`, `tasks/`가 있는 구조)에 문제가 없는지
  주기적으로 확인하고 싶을 때
- 자동 실행이 아니라 **명시적으로 호출됐을 때만** 실행한다 (크론 자동화·PR 자동생성은
  이 스킬의 범위 밖 — 1인 로컬 환경에는 과잉설계로 판단됨, 출처:
  `multiagent/tasks/silvel-meta-technique-review/`)

## 실행 방법

```bash
python3 ~/.claude/skills/ai-readiness-cartography/score_cartography.py --target <진단대상경로>
```

- `--target` 생략 시 현재 디렉터리를 진단 대상으로 사용
- `--output <경로>` 로 리포트를 파일로 저장 가능 (기본은 stdout)
- 예: 이 하네스 자체를 진단하려면 `--target /home/edge_ai/multiagent`
- 예: 다른 프로젝트(hwpx-skill 등)를 진단하려면 해당 경로를 `--target`으로 지정

리포트를 파일로 남길 때는 호출한 task 폴더의 `artifacts/ai-readiness-report.md`에
저장하는 것을 기본 관례로 한다:

```bash
python3 ~/.claude/skills/ai-readiness-cartography/score_cartography.py \
  --target /home/edge_ai/multiagent \
  --output /home/edge_ai/multiagent/tasks/<현재-task>/artifacts/ai-readiness-report.md
```

## 진단 카테고리 (100점 만점, 7개 균등 배분)

MultiAgent Orchestrator 고유 구조에 맞게 재정의된 카테고리 — 일반적인 소프트웨어
품질 지표(테스트커버리지·데드코드 등)가 아니라 **파일기반 오케스트레이션 프로토콜
준수도**를 측정한다.

1. **워커 라우팅 명확성** — task.md의 worker/role 표기가 등록된 4워커
   (claude-main/codex-main/codex-critic/gemini) 중 하나인지
2. **태스크 문서 일관성** — task.md 필수 헤더(메타/Goal/Constraints/Acceptance
   Criteria/Worker Plan) 존재, context.md 글자수 제한(1500자) 준수
3. **브리프 재사용성** — brief.md가 고정 규약 문구를 포함하는지, 1200자 제한 준수
4. **승인 게이트 준수** — result.md가 있는 워커는 task.md의 `workers_approved`에
   기록돼 있는지
5. **검증 루프 준수** — status가 `done`인 작업은 log.md에 `[VERIFICATION]` 기록이
   있는지
6. **문서 최신성** — `_shared/*.md`가 참조하는 상대경로(백틱으로 감싼
   `_shared/...`·`_templates/...`)가 실제로 존재하는지
7. **토끼굴 관리** — log.md의 `[DISCOVERY]` 라인이 `session=` 필드를 포함하는지
   (orchestrator-rules.md §4.3 형식 요건)

## 결과 해석

- 각 카테고리 점수가 낮을수록 리포트의 "우선순위 액션" 절에 구체적 위반 항목이
  나열된다 (파일 경로 + 사유)
- 이 리포트는 진단만 한다 — 실제 수정은 사용자 확인 후 별도로 진행할 것
  (스킬이 자동으로 파일을 고치지 않음)
- 문서 최신성·토끼굴 관리 항목은 오탐 가능성이 있다(정적 패턴 매칭 한계) —
  100점이 아니어도 항목별로 실제 사안인지 먼저 확인 후 대응

## 한계 (알고 시작할 것)

- 정적 검사만 수행 — 문서 내용의 "의미"나 브리프 품질의 맥락적 정확성은 판단하지
  않는다(예: 브리프에 규약 문구가 있어도 내용 자체가 부실할 수 있음)
- "에이전트가 실제로 얼마나 헤맸는가"(강의 원본의 탐색비용 관점)는 측정하지 않는다
  — 세션 로그 분석이 필요한 영역이라 이 스킬의 범위 밖(Token Efficiency 계열 도구
  몫, 이번 스킬에는 미포함하기로 결정됨)
