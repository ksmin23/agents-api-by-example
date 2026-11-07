# 공통 코드

`common.py`: 저장 Agent ID의 최소 복구 기록 저장(save_agent_reference), 설정 로딩, metadata 생성, 오류 이벤트 확인, 소유 자원 취소·삭제·404 확인과 분할 셀의 오류 시 정리와 추가 자원 종료를 담당합니다.

`extensions.py`: Skill의 단순 metadata 읽기·Skill/Plugin ZIP 준비, 중복 호출 캐시, 승인 UI/fixture를 제공합니다.

`deployment.py`: Docker 실행, 사내 패키지 준비, 산출물 다운로드, OTLP transport·JSONL 해석·flush/종료와 운영 상태 관리를 담당합니다.

`validation.py`: 테스트·검증 실행 사본에서만 사용하는 CSV 정답 계산, 지표·보고서·도구 실행 검증, 최종 검증 기록을 담당합니다. 노트북 원본에서는 가져오지 않습니다.

세션 생성·agent/environment/tools 설정·실행·결과 수신·다운로드는 노트북에서 직접 학습합니다. `scripts/notebook_validation.py`는 검증 실행기가 읽은 사본에만 검사와 기록을 추가하고 원본의 최종 `finally` 정리를 유지합니다. 2–14장의 분할 셀에서는 단계 오류 정리 후 실패를 기록하고 최종 정리 직전에 결과를 검사합니다. 실행 루프를 helper로 감싸거나 독자 Trace를 수집하지 않습니다.

자세한 범위는 [작성 규칙](../../docs/authoring.md)과 [실습 안내와 검증 범위](../../docs/validation.md)을 확인하세요.
