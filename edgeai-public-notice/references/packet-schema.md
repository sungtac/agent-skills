# EdgeAI 공고 검토 패킷 규격

패킷은 자유로운 장문 요약이 아니라 다음 단계가 재해석 없이 사용할 수 있는 구조화된 인계자료다. 실제 출력에서는 표 또는 YAML 유사 목록으로 표현해도 되지만 필드 의미는 유지한다.

## 공통 메타정보

- `case_id`: 공고 검토 건 식별자
- `as_of`: 분석 기준일시
- `notice_id`: 공고명·공고번호·버전
- `document_ids`: 사용 문서 목록
- `selected_unit_id`: 실제 작성·전략 대상 선택단위
- `status`: `READY`, `RESTRICTED`, `EVIDENCE_PENDING`, `HOLD`

## 자료 및 사실

- `document_id`, `filename`, `type`, `date`, `version`, `officiality`, `use_status`
- `fact_id`: 확인된 사실 식별자
- `fact`: 공고 또는 자료에 직접 기재된 내용
- `source`: 문서 ID·페이지·절·표
- `fact_status`: `CONFIRMED`, `PARTIAL`, `PENDING`, `MISSING`, `CONFLICT`, `NOT_APPLICABLE`
- `fact_type`: 공고 사실·회사 사실·기관 사실

## 판단

- `claim_id`: 보고서·전략에 사용할 주장 식별자
- `claim`: 핵심 판단 문장
- `claim_type`: 사실·추론·판단·전략상 추론
- `evidence`: 관련 fact_id와 source
- `strength`: 확정·조건부·보류
- `use_status`: 본문 사용 가능·표현 완화·검토 메모만·사용 금지
- `change_condition`: 추가자료로 판단이 바뀌는 조건

## 기관

- `org_id`, `name`, `org_status`, `execution_role`
- `necessity`: 공고상 필수·수행상 필요·평가상 유리·확인 필요
- `eligibility_status`, `capability_status`, `role_status`
- `edgeai_relation`: 보완·중복·공백
- `body_recommendation`: 본문 포함·표만·보완 후·제외
- `allowed_wording`, `prohibited_wording`

## 조치

- `action_id`, `action`, `reason`, `priority`
- `owner`, `due_date`, `dependency`, `deliverable`
- `if_unresolved`: 미확인 시 문서·전략 처리 방식

