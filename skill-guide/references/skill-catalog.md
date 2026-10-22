# 설치 스킬 자동 카탈로그

> 이 파일은 `generate_skill_guide.py`가 manifest.json과 각 SKILL.md에서 생성한다.

- `ai-readiness-cartography` — Static, read-only diagnostic scorer for file-based MultiAgent Orchestrator harnesses (tasks/<task>/{task.md,context.md,log.md,workers/}). Scores 7 categories (worker routing clarity, task doc consistency, brief reusability, approval gate compliance, verification loop compliance, doc freshness, rabbit-hole management) and produces a Markdown report with priority actions. Use when the user says "카토그래피 돌려줘/실행해줘/검사해줘", "AI 레디니스 점검해줘", "하네스 진단해줘/헬스체크", "diagnose/cartography the harness", or asks how AI-agent-friendly the multiagent tasks/ structure is.
  - Codex: supported / Claude: supported / 의존성: python3
- `codex-image` — Generate images via Codex CLI's built-in image_gen tool (gpt-image-2). OAuth auth — no API key needed. Codex CLI의 내장 image_gen 도구로 이미지 생성. OAuth 인증으로 API 키 불필요. Usage: /codex-image cherry blossom hanok, /codex-image --size 1024x1536 space cat, /codex-image --quality high seoul night
  - Codex: supported / Claude: limited / 의존성: Codex image_gen
- `design-taste-frontend` — Anti-slop frontend skill for landing pages, portfolios, and redesigns. The agent reads the brief, infers the right design direction, and ships interfaces that do not look templated. Real design systems when applicable, audit-first on redesigns, strict pre-flight check.
  - Codex: supported / Claude: supported / 의존성: 없음
- `diagnosing-bugs` — Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
  - Codex: supported / Claude: supported / 의존성: shell, read access
- `diagram-design` — Diagram design reference library (14 types — architecture, flowchart, sequence, state, ER, timeline, swimlane, quadrant, nested, tree, org chart, layers, venn, pyramid). In ppt-master this is consumed by the Executor when hand-authoring diagram-type SVG pages — it is NOT a standalone HTML generator here. Read for deep per-type layout conventions.
  - Codex: supported / Claude: supported / 의존성: 없음
- `edgeai-public-notice` — Use for 지원사업 분석, 공고 분석, 공고문 분석, 공고문 검토, 공고 검토, or related requests involving Korean public notices, RFPs, application eligibility, participation decisions, internal reports, or detailed participation strategies from EdgeAI's perspective. Run a conversational, evidence-first workflow and ask only for decision-blocking missing information.
  - Codex: supported / Claude: supported / 의존성: 없음
- `handoff` — Compact the current conversation into a handoff document for another agent to pick up.
  - Codex: supported / Claude: supported / 의존성: temporary directory
- `last30days` — Research what people actually say about any topic in the last 30 days. Pulls posts and engagement from Reddit, X, YouTube, TikTok, Hacker News, Polymarket, GitHub, and the web. Includes a doctor health check to diagnose broken or missing sources.
  - Codex: limited / Claude: supported / 의존성: network, web/search access
- `native-enhance-pptx` — Enhance a finished PPTX while keeping visible content and layout stable. Use for adding or replacing speaker notes, narration audio, auto-advance timing, or slide transitions through direct OOXML. Do not use for redesign, raw template filling, SVG-generated project narration, or changing slide content.
  - Codex: supported / Claude: supported / 의존성: PPTX/OOXML tooling
- `orchestration` — AgentLayer로 멀티 에이전트 오케스트레이션. worker N개(claude·codex·gemini)를 각각 git worktree+tmux window에 띄워 태스크를 병렬로 dispatch하고, 완료를 기다렸다가 결과를 취합·비교한다. "worker 2개 만들어서 같은 태스크 시켜줘", "claude랑 codex한테 A/B로 시켜봐", "서로 다른 태스크 나눠서 병렬로", "/orchestration" 등으로 트리거. 머지는 기본적으로 사용자 몫이다.
  - Codex: conditional / Claude: conditional / 의존성: git, tmux, agentlayer, worker CLIs
- `ppt-master` — Post-router owner for authoring or regenerating presentation visuals through the PPT Master SVG pipeline: new decks from source material or a topic, PPTX re-architecture, generation from an already-created reusable SVG-template workspace, and shared SVG steps only after a strict 1:1 beautify workflow explicitly hands off. Read workflows/routing.md first. Do not use for ambiguous existing-PPTX optimization, reusable-template creation, raw-PPTX native filling, or finished-PPTX native enhancement; those are pre-route or standalone workflow requests.
  - Codex: supported / Claude: supported / 의존성: PPT/SVG pipeline
- `ppt-template-fill` — Fill a raw PowerPoint (.pptx) template with new content by cloning and patching native slides — no SVG conversion, original design preserved, verified through a mandatory OfficeCLI overflow/render loop. Use whenever the user supplies an existing .pptx template or deck plus new material or a topic and wants a generated PPTX, even if they don't say "template" — "use this PPT template to generate a PPTX", "fill this deck with the new content", "replace the copy in this PowerPoint", "keep the original design and swap in this material", "이 템플릿에 내용 채워줘", "이 PPT 양식으로 만들어줘", "기존 PPT 디자인 그대로 내용만 교체해줘". Do NOT use for reusable template package creation (ppt-master create-template), 1:1 beautify, SVG-pipeline deck generation, or finished-PPTX enhancement (native-enhance-pptx).
  - Codex: conditional / Claude: conditional / 의존성: PPTX, OfficeCLI
- `skill-guide` — Use when the user says 스킬설명, 스킬 설명서, 스킬 목록, 사용 가능한 스킬, 또는 asks what installed skills do. Show the shared Codex and Claude user-skill list with concise descriptions, trigger guidance, and system-skill exclusions.
  - Codex: supported / Claude: supported / 의존성: shared-skills manifest
- `tdd` — Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
  - Codex: supported / Claude: supported / 의존성: project test runner
