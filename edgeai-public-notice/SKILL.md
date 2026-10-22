---
name: edgeai-public-notice
description: "Use for 지원사업 분석, 공고 분석, 공고문 분석, 공고문 검토, 공고 검토, or related requests involving Korean public notices, RFPs, application eligibility, participation decisions, internal reports, or detailed participation strategies from EdgeAI's perspective. Run a conversational, evidence-first workflow and ask only for decision-blocking missing information."
---

# EdgeAI 공고 검토

이 스킬은 공고 검토를 한 번에 끝내는 거대한 응답이 아니라, 사용자가 자료를 순차적으로 제공하고 부족한 사실을 확인해 가는 대화형 작업으로 운영한다. 공고 사실, 회사 사실, 분석 판단, 전략 제안을 분리하고, 각 단계의 결과를 다음 단계가 재해석하지 않도록 패킷 형태로 유지한다.

## Operating modes

사용자의 목적과 자료 상태에 따라 필요한 모드만 실행한다.

- **분석**: 공고·회사·기관·선택단위·리스크를 분석하고 `FACT_PACKET`과 `ANALYSIS_PACKET`을 만든다.
- **기관 상세**: 외부 실명 기업·기관이 3개 이상일 때만 A-2 분기를 실행해 `ORG_PACKET`을 만든다.
- **내부 보고**: 경영진 또는 내부 의사결정용 1~2페이지 보고서를 `REPORT_PACKET`으로 만든다.
- **참여전략**: 실제 참여 의사가 있거나 전략이 필요한 경우 포지션·R&R·산출물·예산·일정·로드맵을 `STRATEGY_PACKET`으로 만든다.
- **문안·스타일**: 사업계획서·제안서·검토보고서 문안을 작성한 뒤 스타일 참고자료를 후처리로 적용한다. 스타일 자료는 사실 근거가 아니다.
- **최종검증**: 주장별 근거, 표현 강도, 금지 주장, 문서 버전, 분량, 제출 형식을 점검한다.

세부 패킷 필드는 [references/packet-schema.md](references/packet-schema.md), 실행 흐름과 대화 규칙은 [references/workflow.md](references/workflow.md)를 따른다. 모드별 출력 필드는 [references/module-a.md](references/module-a.md), [references/module-b.md](references/module-b.md), [references/module-c.md](references/module-c.md)를 필요한 모드에서만 읽는다.
실제 문안·스타일·최종검증은 [references/module-d.md](references/module-d.md), [references/module-s.md](references/module-s.md), [references/module-q.md](references/module-q.md)를 읽는다. 입력 질문은 [references/intake-questions.md](references/intake-questions.md)를 따른다. 이전 작업에서 기록된 개선사항은 `state/improvements.jsonl`이 있으면 작업 시작 전에 읽고 현재 판단에 반영한다.

## Non-negotiable evidence rules

- 최신 공식 공고·정정공고·작성양식을 자격, 일정, 예산, 신청구조, 산출물의 사실 기준으로 삼는다.
- 사용자 지시는 분량, 독자, 문서 형태, 전략적 선호에 반영하되 공식 공고의 요건을 바꾸지 못한다. 충돌은 명시한다.
- 사실이 없으면 만들지 말고 `자료 없음`, `검증 필요`, `추론`, `충돌`, `해당 없음`을 구분한다.
- 공고상 사실, 회사자료상 사실, 분석 판단, 전략상 추론을 별도 기록한다.
- MOU·LOI·구매의향·구매확약·계약, 수요처·공급사·외주사·공동연구기관·시험기관을 혼동하지 않는다.
- 지원·입찰 참가·수행·실증·선정·낙찰을 서로 다른 판단으로 표현한다.
- 자격 미충족, 마감 경과, 지역 요건 미충족, 공동수급 불가 등 차단 사유를 보완전략으로 포장하지 않는다.
- “우회전략” 대신 “합법적 보완·포지션 조정 전략”을 사용한다. 외부기관·포지션 조정은 공고상 허용 여부가 확인된 경우에만 제안한다.
- 엣지에이아이의 AI·NPU·온디바이스·비전 역량은 회사자료 또는 증빙에서 확인된 경우에만 확정 표현으로 사용한다.
- 제출용 본문과 내부 검토 메타정보를 분리한다. Claim ID, 상태 태그, 변경이력은 검토 패킷에 남기고 최종 본문에는 불필요한 내부 태그를 남기지 않는다.

## Conversational behavior

작업 시작 시 다음을 먼저 확인한다.

1. 현재 모드와 사용 목적
2. 공고명·공고 유형·기준일·최신 버전
3. 신청 형태와 엣지에이아이의 역할
4. 작성 대상 선택단위
5. 현재 확보 자료와 핵심 공백

부족한 내용이 있으면 한 번에 필요한 질문을 과도하게 늘리지 말고, 의사결정을 막는 항목부터 질문한다. 질문은 `필요한 정보 / 필요한 이유 / 미제공 시 처리` 형식으로 제시한다. 공고명 또는 핵심 공고요건이 없으면 특정 공고의 확정 판단·보고서·전략을 만들지 말고 자료 요청 또는 추천형 분석으로 제한한다.

## Output discipline

- 분석은 전수성과 근거를 우선하고, 보고서는 결론·리스크·즉시조치를 우선한다.
- 외부기관 상세 분석은 3개 이상일 때 A등급 전수, 핵심 B등급 상세, C등급 요약으로 분량을 조절한다.
- 1~2페이지는 본문 기준으로 적용하고 상세 근거표·기관표·보완자료표는 별도 부록 또는 검토 패킷으로 분리한다.
- 선택단위가 여러 개면 작성 대상 선택단위를 별도로 지정한다. 지정되지 않으면 단일 과제처럼 쓰지 않는다.
- 각 단계 종료 시 현재 상태, 핵심 판단, 미해결 질문, 다음 단계 입력을 짧게 인계한다.

## Quality gate

최종 응답 전에 자료 생성 여부, 공식자료 우선 여부, 판단 강도 보존 여부, 선택단위·기관 역할 혼동 여부, 금지 표현 여부, 근거와 변경이력의 연결 여부를 확인한다. 새 사실이나 판단을 추가했다면 근거 또는 `전략상 추론` 표시가 없이는 출력하지 않는다.

## Harness and self-improvement

수정 후에는 `scripts/validate_harness.py`를 실행한다. 이 하네스는 패킷 필수 필드, 상태값, 금지 표현, A-2 분기, 양쪽 배포본의 동기화를 점검한다. 실제 작업에서 발견한 재현 가능한 오류는 `scripts/record_improvement.py`로 `state/improvements.jsonl`에 기록한다.

공용 원본은 `/home/edge_ai/edgeai-public-notice`다. Codex·Claude 배포본은 `scripts/sync_skill.py`로 갱신한다. 배포 후 두 경로에 동일한 해시가 있는지 하네스로 확인한다. 모델이 스스로 사실을 추가하거나 파일을 임의로 수정하는 방식의 자가개선은 허용하지 않으며, 개선 기록은 반드시 근거·재현 조건·수정 내용·검증 결과를 가진 검토 가능한 항목으로 남긴다.
