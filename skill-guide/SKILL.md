---
name: skill-guide
description: "Use when the user says 스킬설명, 스킬 설명서, 스킬 목록, 사용 가능한 스킬, 또는 asks what installed skills do. Show the shared Codex and Claude user-skill list with concise descriptions, trigger guidance, and system-skill exclusions."
---

# 스킬 설명서

사용자가 `스킬설명`, `스킬 설명서`, `스킬 목록`, `사용 가능한 스킬 알려줘` 또는 유사한 표현을 사용하면 실행한다.

아래 목록은 현재 Codex와 Claude에서 공동으로 사용하는 사용자 설치 스킬이다. 시스템 기본 스킬은 별도 요청이 없는 한 제외한다.

실제 설치 상태와 Codex·Claude별 호환성은 [references/skill-catalog.md](references/skill-catalog.md)를 우선 확인한다. 정적 설명과 실제 목록이 다르면 카탈로그와 설치 디렉터리 차이를 사용자에게 알린다.

## 공고·업무 분석

- `edgeai-public-notice`: 지원사업·공고·공고문을 엣지에이아이 관점에서 분석하고, 부족한 자료를 대화로 확인하며 내부보고서·참여전략·후속 문안까지 단계적으로 만든다. 주요 키워드는 `지원사업 분석`, `공고 분석`, `공고문 분석`, `공고문 검토`, `공고 검토`다.
- `ai-readiness-cartography`: 파일 기반 멀티에이전트 하네스의 라우팅·문서 일관성·승인·검증 루프·문서 최신성 등을 읽기 전용으로 진단하고 개선 보고서를 만든다. `하네스 진단`, `AI 레디니스 점검`, `카토그래피` 요청에 사용한다.
- `orchestration`: Claude·Codex·Gemini 등의 워커를 병렬로 배치하고 태스크를 나누어 결과를 취합하는 멀티에이전트 오케스트레이션 스킬이다.
- `handoff`: 현재 대화와 작업상태를 다음 에이전트가 이어받을 수 있는 인수인계 문서로 정리한다.
- `diagnosing-bugs`: 오류·성능저하·실패 원인을 단계적으로 진단하는 디버깅 스킬이다. `debug`, `diagnose`, `고장`, `느려짐` 요청에 사용한다.
- `tdd`: 테스트를 먼저 작성하고 Red-Green-Refactor 방식으로 기능을 구현하거나 버그를 수정한다.

## 문서·프레젠테이션·디자인

- `ppt-master`: SVG 기반 PPT Master 파이프라인으로 새 프레젠테이션을 만들거나 구조를 재설계한다.
- `ppt-template-fill`: 기존 PPT 템플릿의 디자인을 유지하면서 내용을 교체하고, 렌더링·오버플로를 검증한다.
- `native-enhance-pptx`: 완성된 PPTX의 레이아웃을 유지하면서 발표자 노트·내레이션·자동재생·전환효과 등을 OOXML로 보강한다.
- `diagram-design`: 아키텍처·플로차트·시퀀스·상태도·ERD·타임라인 등 다양한 다이어그램의 구조와 배치 원칙을 제공한다.
- `design-taste-frontend`: 랜딩페이지·포트폴리오·리디자인을 템플릿처럼 보이지 않도록 설계하고 구현한다.
- `codex-image`: Codex CLI의 이미지 생성 기능으로 프롬프트 기반 이미지를 만든다.

## 조사·분석

- `last30days`: Reddit·X·YouTube·TikTok·Hacker News·GitHub 등에서 최근 30일의 반응과 언급을 조사한다.

## 사용 방법

1. 원하는 스킬 이름을 직접 말한다. 예: `edgeai-public-notice로 공고 검토해줘`.
2. 목적이나 키워드만 말해도 관련 스킬을 선택한다.
3. 여러 스킬이 관련되면 필요한 순서와 역할을 먼저 설명한다.
4. 스킬이 없거나 시스템 기본 스킬에 해당하면 그 사실을 표시하고 대체 방법을 제안한다.

## 표시 형식

요청 시 다음 순서로 출력한다.

1. 현재 공용 사용자 스킬 수
2. 분야별 스킬명과 한 줄 설명
3. 대표 실행 키워드
4. 시스템 기본 스킬 제외 여부
5. 특정 스킬을 선택해 자세히 볼 수 있다는 안내
