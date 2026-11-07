# Function Tool 직접 응답: 심화 자료

[7장](../../notebooks/chapters/07_function_tools.ipynb)의 기본 실행은 공식 `function_tool()`과 `tool_handlers`를 사용합니다. Python 함수는 직접 호출할 수 있으며 SDK 어댑터는 인자를 검증하고 반환값을 직렬화합니다. 이미 직렬화된 SDK 반환값을 다시 `json.dumps()`하지 않습니다.

## pending action을 직접 처리할 때

자동 `tool_handlers`와 아래 직접 처리를 같은 호출에 중복 적용하지 않습니다. 현재 pending action의 `turn_id`·`call_id`를 사용합니다.

```python
for action in event.session.required_actions:
    if action.type != "function_call" or action.name != "get_sales_target":
        raise RuntimeError("Unsupported action")
    # sales_target_tool validates the argument dict and returns serialized output.
    output = sales_target_tool(action.arguments)
    client.beta.agents.sessions.events.create(
        event.session.id,
        events=[{
            "type": "agent.session.input.tool_result",
            "turn_id": action.turn_id,
            "call_id": action.call_id,
            "success": True,
            "output": output,
        }],
    )
```

위 코드는 이벤트루프의 `agent.session.requires_action` 분기에 넣는 코드입니다. 인자·권한 위반은 안전한 오류 코드와 `success=False`로 반환하고 원래 예외 본문은 보내지 않습니다.

부작용이 있는 함수는 session/turn/call별 결과를 저장하고 같은 호출의 재전달에는 재실행하지 않습니다. 실행 후 저장 전에 중단됐다면 업무 시스템의 결과를 확인해야 합니다. Trace만으로 중복 실행 문제를 해결할 수는 없습니다. [11장 구현](../../notebooks/chapters/11_guardrails_approvals.ipynb)은 캐시와 승인을 포함한 직접 처리를 보여줍니다.

[공식 Functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions)
