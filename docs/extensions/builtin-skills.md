# OpenAI-hosted 기본 스킬 확인

사용자가 `environment.skills`에 등록한 Custom Skill과 hosted 이미지에 포함된 기본 스킬은 다릅니다. CSV 분석은 Spreadsheets의 적용 대상이므로 별도 등록 없이 스킬 참고가 언급될 수 있습니다.

2026-11-03 별도의 Skill·Plugin·템플릿 없이 만든 실제 환경에서 `documents`, `Presentations`, `Spreadsheets`를 확인했습니다. `/opt/artifact-sdk/skills/{documents,presentations,spreadsheets}/SKILL.md`와 `/root/.codex/skills/builtins/` 아래에서 같은 이름·설명을 관찰했습니다. 이 목록과 경로는 이미지별로 달라질 수 있으며 고정된 API 계약이 아닙니다.

## 등록 메타데이터

연결된 세션을 삭제하기 전에 확인합니다.

```python
environment = client.beta.agents.environments.retrieve(session.environment.id)
print([skill.to_dict() for skill in environment.skills])
```

실측한 기본 환경의 응답은 `skills=[]`였지만 위 기본 파일들은 존재했습니다. 따라서 이 필드를 기본 스킬 전체 목록으로 해석하지 않습니다. 9장은 등록한 `csv-report`를 이 필드로 확인합니다.

## 선택: 실제 파일 목록 확인

기존 세션에 아래 요청을 별도 Turn으로 보내면 모델·sandbox 사용료가 발생할 수 있습니다. 일반 실습에서는 자동 실행하지 않습니다.

```python
inventory_task = """Read-only inventory: run the following command in the sandbox,
then read only the name and description frontmatter of each SKILL.md.
Do not install packages, modify files, or perform any skill workflow.
find -L /opt/artifact-sdk/skills /root/.codex/skills/builtins -name SKILL.md -print
"""
with client.beta.agents.sessions.stream(session.id, input=inventory_task).with_result_collection() as stream:
    for event in stream:
        if event.type == "agent.session.turn.item.done" and event.item.type == "command_execution":
            print(event.item.exit_code, event.item.output)
    result = stream.get_final_result()
print(result.output_text)
```

모델의 “사용하겠다”는 문구, 파일 존재, 실제 지침 읽기, 번들 스크립트 실행은 각각 다른 증거입니다. 실행 과정은 Platform Trace에서 확인하고, 9장의 증거 파일·스크립트 검증과 구분합니다.

[공식 환경 조회](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/environments/methods/retrieve) · [7장](../../notebooks/chapters/07_function_tools.ipynb) · [9장](../../notebooks/chapters/09_skills.ipynb)
