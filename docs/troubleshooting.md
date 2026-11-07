# 문제 해결

| 증상 | 확인할 항목 |
| --- | --- |
| 노트북에서 패키지를 찾지 못함 | `uv sync --locked`와 `.venv` 커널 선택 |
| Book CLI가 실행되지 않음 | Node.js 22 LTS 설치, docs 의존성 동기화 |
| Colab 노트북이나 ZIP 다운로드 링크가 없거나 열리지 않음 | 제공자는 배포 산출물을 다시 빌드하고 언어별 다운로드 파일 포함 여부를 확인합니다. 학습자는 [독립 Colab 안내](colab.md)에 따라 제공된 파일을 업로드합니다. GitHub 접근은 필요하지 않습니다. |
| Colab 패키지 설치 실패 | 설치 셀의 오류와 공개 PyPI 접근을 확인합니다. requirements 파일을 GitHub에서 내려받지 않습니다. 설치 후에도 import 오류가 남으면 런타임을 다시 시작하고 준비 셀부터 재실행합니다. |
| Colab에서 helper·데이터·예제 파일을 찾지 못함 | 독립 실행본을 사용하고 포함 파일 준비 셀을 순서대로 실행합니다. 생성 파일을 직접 수정하지 말고 제공자에게 최신 실행본을 요청합니다. |
| 의존성 변경 후 CI 실패 | uv.lock 갱신 후 build_colab.py로 독립 실행본 재생성 |
| Pages에서 경로가 깨짐 | BASE_URL과 저장소명, Pages source 설정 |
| uv에서 잠금 파일이 오래됐다는 오류 | UV_DEFAULT_INDEX 등 인덱스 환경 설정을 확인합니다. `uv sync --locked --default-index https://pypi.org/simple`로 공개 인덱스를 명시해 비교하고 후속 uv run에도 같은 인덱스를 지정합니다. 자격 증명은 출력하지 않습니다. |
| SOCKS proxy 관련 socksio ImportError | SOCKS가 필요한 환경에서만 `uv run --group proxy jupyter lab`을 사용합니다. 회사 정책에 맞는 프록시를 유지하며 일반 사용자에게 SOCKS 패키지를 일괄 설치하지 않습니다. |
| 13장 또는 교재 빌드에서 선택 패키지 누락 | 메모리 관측은 `uv run --group telemetry jupyter lab`, Collector는 `uv run --group telemetry-otlp jupyter lab`, 빌드는 `uv run --group docs python scripts/build_artifacts.py --target sites`를 사용합니다. |
| 장의 API 기능을 실행할 수 없음 | 검증 범위 문서·API 접근 권한·SDK 지원 여부 |

이 저장소의 오프라인 검사가 통과해도 Agents API 접근 권한이나 라이브 동작이
검증된 것은 아닙니다. 문서 빌드와 실제 API 검증 결과를 별도로 기록합니다.
