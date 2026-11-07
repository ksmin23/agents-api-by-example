"""Fresh-kernel deployment notebooks. Docker and paid API work have separate switches."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import nbformat
from nbclient import NotebookClient
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from update_intro_progress import update

CHAPTERS = {12: "12_self_hosted", 13: "13_hooks_telemetry", 14: "14_operations"}


def run(chapter, *, docker=False, live=False):
    slug = CHAPTERS[chapter]
    notebook = nbformat.read(ROOT / f"notebooks/chapters/{slug}.ipynb", as_version=4)
    from check_notebooks import validate_api_tags
    api_cells = validate_api_tags(notebook)
    for cell in notebook.cells:
        if "deployment_configuration" in cell.metadata.get("tags", []):
            assert "RUN_DOCKER = False" in cell.source and "RUN_LIVE = False" in cell.source
            if docker:
                cell.source = cell.source.replace("RUN_DOCKER = False", "RUN_DOCKER = True")
            if live:
                cell.source = cell.source.replace("RUN_LIVE = False", "RUN_LIVE = True")
            if chapter == 12 and docker and not live:
                cell.source = cell.source.replace("RUN_PACKAGE_CHECKS = False", "RUN_PACKAGE_CHECKS = True")
            if chapter == 13 and docker and not live:
                cell.source = cell.source.replace("RUN_LOCAL_CHECKS = False", "RUN_LOCAL_CHECKS = True")
            if chapter == 13 and os.environ.get("TUTORIAL_EXPORT_TRACES") == "1":
                cell.source = cell.source.replace("EXPORT_TRACES = False", "EXPORT_TRACES = True")
    from notebook_validation import instrument_notebook
    instrument_notebook(notebook, slug, live=live, docker=docker)
    print(f"Chapter {chapter}: docker={docker}, api={live}", flush=True)
    update(chapter, note=f"새 커널 검증 시작. Docker={docker}, 실제 API={live}.")
    error_name = None
    with tempfile.TemporaryDirectory(prefix="tutorial-deployment-kernel-") as temporary:
        kernel = Path(temporary) / "kernels/deployment-check"
        kernel.mkdir(parents=True)
        (kernel / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                    "display_name": "Deployment validation",
                    "language": "python",
                }
            )
        )
        old = os.environ.get("JUPYTER_PATH")
        os.environ["JUPYTER_PATH"] = temporary
        env = dict(os.environ)
        env.pop("OPENAI_LOG", None)
        if docker or live:
            env.pop("TUTORIAL_OFFLINE_CHECK", None)
        else:
            from check_notebooks import GUARD

            notebook.cells.insert(0, nbformat.v4.new_code_cell(GUARD))
            env["TUTORIAL_OFFLINE_CHECK"] = "1"
        if not live:
            for name in ["OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY", "CODEX_API_KEY"]:
                env.pop(name, None)
        try:
            NotebookClient(
                notebook,
                timeout=900,
                kernel_name="deployment-check",
                coalesce_streams=True,
                skip_cells_with_tag="skip-execution" if live else "requires_api",
                resources={"metadata": {"path": str(ROOT)}},
            ).execute(env=env)
        except Exception as error:
            error_name = type(error).__name__
        finally:
            if old is None:
                os.environ.pop("JUPYTER_PATH", None)
            else:
                os.environ["JUPYTER_PATH"] = old
    serialized = nbformat.writes(notebook)
    values = dotenv_values(ROOT / ".env.local")
    for name in ["OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY"]:
        if any(
            secret and secret in serialized for secret in [values.get(name), os.environ.get(name)]
        ):
            raise RuntimeError("refusing_to_save_secret")
    mode = "api-docker" if live and docker else "api" if live else "docker" if docker else "offline"
    target = ROOT / f"outputs/deployment-validation/{slug}.{mode}.executed.ipynb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized)
    if error_name:
        update(
            chapter,
            **({"live": "실패"} if live else {"offline": "실패"} if not docker else {}),
            note=f"검증 실패({error_name}). 실행 사본과 state.json을 확인합니다.",
        )
        print(f"FAIL {chapter}: {error_name}", flush=True)
        return False
    if docker and (chapter not in {12, 13} or not live):
        summary = json.loads((ROOT / f"outputs/deployment/{slug}/latest.json").read_text())
        assert summary["status"] == "passed" and summary["checks"]
        assert not summary["cleanup_errors"]
        assert all(
            v["removed"] for v in [*summary["containers"].values(), *summary["networks"].values()]
        )
        note = "Docker 실제 실행·결과·생성 자원 부재 확인 통과. requires_api 셀은 --live를 지정할 때만 실행하며, 이 기록은 API 실행·native Hook dispatch 검증과 구분합니다."
        update(chapter, writing="작성 완료", note=note)
    elif not live:
        update(
            chapter,
            writing="작성 완료",
            offline="통과",
            note=f"새 커널 로컬 셀 실행 통과. requires_api {api_cells}개 셀 건너뜀; Docker·API 미실행.",
        )
    if live:
        result = json.loads(
            (
                ROOT
                / f'outputs/deployment-api/{"12_self_hosted_api" if chapter == 12 else slug}/latest.json'
            ).read_text()
        )
        assert result["status"] == "passed" and result["sessions"] and result["turns"]
        assert all(v["verified_absent"] for v in result["sessions"].values())
        assert not result["cleanup_errors"]
        if chapter == 13:
            assert result["checks"]["callbacks_source"] == "actual_agents_api"
            if docker:
                transport = json.loads(
                    (ROOT / "outputs/deployment/13_api_telemetry/latest.json").read_text()
                )
                assert (
                    transport["status"] == "passed"
                    and transport["checks"]["actual_api_events_exported"]
                )
                assert all(
                    v["removed"]
                    for v in [*transport["containers"].values(), *transport["networks"].values()]
                )
        if chapter == 14:
            assert (
                result["checks"]["root_turn_count"] == 1
                and not result["checks"]["input_resubmitted"]
            )
        if chapter == 12:
            provider = json.loads(
                (ROOT / "outputs/deployment/12_executor_compute/latest.json").read_text()
            )
            assert provider["status"] == "passed"
            assert all(
                v["removed"]
                for v in [*provider["containers"].values(), *provider["networks"].values()]
            )
        update(
            chapter,
            writing="개편 완료",
            live="통과",
            note=f'개편 후 실제 {"Self-hosted" if chapter == 12 else "OpenAI-hosted"} API 실행·결과·세션 삭제 확인. 결과: outputs/deployment-api/{"12_self_hosted_api" if chapter == 12 else slug}/latest.json. native Hook dispatch·실제 청구 검증은 미실행입니다.',
        )
    print(f"PASS {chapter}: {target.relative_to(ROOT)}", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chapter", type=int, choices=CHAPTERS)
    group.add_argument("--all", action="store_true")
    parser.add_argument(
        "--docker", action="store_true", help="Authorize local Docker resources and fault injection"
    )
    parser.add_argument("--build", action="store_true", help="Build sample images before execution")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Paid API; chapters 13/14 use hosted, chapter 12 requires --docker and a dedicated executor key",
    )
    args = parser.parse_args()
    if args.live and (args.chapter == 12 or args.all):
        from tutorial_helpers.deployment import executor_key

        if not args.docker:
            parser.error(
                "Self-hosted chapter 12 also requires --docker; no session or compute was created"
            )
        if not executor_key(ROOT):
            parser.error(
                "OPENAI_EXECUTOR_API_KEY is required for chapter 12; run --chapter 13/14 --live independently"
            )
    if args.build:
        from tutorial_helpers.deployment import build_images

        print(build_images(ROOT, executor=args.chapter == 12 or args.all), flush=True)
    for number in (CHAPTERS if args.all else [args.chapter]):
        if not run(number, docker=args.docker, live=args.live):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
