# 다국어 교재 관리

`notebooks/`를 유일한 원본으로 유지합니다. 한국어 본문과 영어 번역 카탈로그를 결합한 작업 사본만 `_build/`에 생성합니다. 셀 ID·코드·메타데이터는 유지하며 Markdown 설명만 번역합니다.

- `translations/en/<원본경로>.json`: 셀 ID 또는 document 키, 원문 SHA-256, 영어 텍스트.
- `translations/glossary.json`: 용어집. 변경하면 번역 갱신이 필요합니다.
- `translations/pages.json`: 원본 경로와 언어 중립 URL slug 대응표. 한국어 URL을 유지합니다.
- `_build/colab/`: 한국어 실행본; `_build/colab/en/`: 영어 실행본. 원본 템플릿은 배포하지 않습니다.
- `_build/packages/colab-notebooks.zip`, `colab-notebooks-en.zip`: 각각 언어별 노트북 17개와 README.
- `_build/book/<target>/`: 한국어 루트와 `en/` 영어 교재를 함께 조립합니다.

배포 빌드는 카탈로그만 읽습니다. 번역을 변경하려면 `uv run python scripts/update_translations.py --refresh`를 명시적으로 실행합니다. 기존 `.env.local`의 API 키·모델을 사용하며 키는 저장하지 않습니다. 실패한 번역 초안은 outputs/translation-drafts/에 보관하고 재시도 시 재사용합니다. 번역 갱신 후 카탈로그 diff를 검토하고 커밋하세요. 자동 생성 영문 노트북을 직접 편집하지 않습니다.

번역기는 fenced code·inline code·URL·명시적 앵커를 보호합니다. 코드 블록 안의 설명용 주석과 복구용 예시 자리표시자는 원본부터 영어로 작성해 양쪽 언어에 동일하게 표시합니다. 실행 프롬프트·출력 예시의 한국어 문자열은 임의로 번역하지 않습니다. 보호 문자열 변경, 제목 단계 변경, 남은 미번역 본문, 원문 해시·용어집 해시 불일치를 거절합니다. 초기 번역의 구조 검사는 전문 번역 감수를 대신하지 않습니다. 모델 요청과 한국어 보고서 제목은 실행 코드에 속하므로 번역하지 않습니다.

언어 전환 모듈은 전체 페이지 이동으로 다른 언어의 설정·검색 색인을 불러옵니다. 각 페이지의 KO/EN 제목 앵커를 대응해 현재 절의 이동도 지원합니다. EN 링크의 GitHub 원본은 한국어 원본이므로 번역 수정은 카탈로그를 이용하세요.

Sites의 BASE_URL은 한국어 빈 값·영어 /en, 프로젝트 Pages는 /agents-api-by-example·/agents-api-by-example/en입니다. 언어별 자산을 독립 빌드하고 한 디렉터리에 조립하므로 기존 배포 명령과 Sites identity를 유지할 수 있습니다.

확인: `scripts/localization.py`, `scripts/check_artifacts.py --target all`, `scripts/check_colab.py --execute --language all`. 원본 해시·코드 셀 동일성·카탈로그 freshness·양쪽 페이지/언어 링크·앵커·다운로드·독립 커널 로딩을 구분합니다. 테스트·배포 결과는 README가 아닌 로컬 `.work/PROGRESS.md`와 `outputs/`에 기록하고 Git과 배포 산출물에서 제외합니다.
