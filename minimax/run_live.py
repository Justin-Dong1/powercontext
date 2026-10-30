"""One real MiniMax task from a clean sample; no model calls without an explicit key."""

from pathlib import Path
import argparse, contextlib, getpass, hashlib, importlib.metadata, json, os, platform, shutil, subprocess, sys, uuid, warnings
from native_runtime import local_server

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--binary",
        type=Path,
        help="Optional local seekdb executable; otherwise use SEEKDB_HOST/PORT",
    )
    p.add_argument("--runs", type=Path, default=Path("runs"))
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Read the API key with hidden input; default model is MiniMax-M3",
    )
    args = p.parse_args()
    if args.interactive:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass("MiniMax API Key (hidden input): ").strip()
        except (EOFError, getpass.GetPassWarning):
            p.error("Hidden input unavailable; use an interactive terminal. No network call was made")
        except KeyboardInterrupt:
            p.exit(130, "\nCancelled; no network call was made\n")
        if not key:
            p.error("API key was empty; no network call was made")
        os.environ["MINIMAX_API_KEY"] = key
        os.environ["MINIMAX_MODEL"] = os.getenv("MINIMAX_MODEL", "").strip() or "MiniMax-M3"
        print("Model: " + os.environ["MINIMAX_MODEL"], file=sys.stderr)
    if not os.getenv("MINIMAX_API_KEY") or not os.getenv("MINIMAX_MODEL"):
        p.error("Set MINIMAX_API_KEY and MINIMAX_MODEL first; no network call was made")
    root = args.runs.resolve() / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    project = root / "project"
    shutil.copytree(HERE / "sample", project)
    env = os.environ.copy()

    def call(command):
        argv = [
            sys.executable,
            str(HERE / "sdd_context.py"),
            "--project",
            str(project),
            "--state",
            str(root / "state.db"),
            "--out",
            str(root / "evidence"),
            command,
        ]
        r = subprocess.run(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf8",
            errors="replace",
            timeout=300,
        )
        (root / (command + ".log")).write_text(r.stdout, encoding="utf8")
        if r.returncode:
            raise RuntimeError(
                "Stage failed: "
                + command
                + "; inspect "
                + str(root / (command + ".log"))
            )
        return json.loads(r.stdout.strip().splitlines()[-1])

    try:
        manager = (
            local_server(args.binary, root / "server")
            if args.binary
            else contextlib.nullcontext(None)
        )
        with manager as endpoint:
            if endpoint:
                env.update(
                    SEEKDB_HOST=endpoint["host"],
                    SEEKDB_PORT=str(endpoint["port"]),
                    SEEKDB_USER=endpoint["user"],
                    SEEKDB_PASSWORD=endpoint["password"],
                )
            call("index")
            before = call("context")
            spec = project / "specs/status.md"
            marker = "reimport-proof-" + uuid.uuid4().hex[:12]
            spec.write_text(
                spec.read_text(encoding="utf8")
                + "\nS-5: Verification reference "
                + marker
                + ".\n",
                encoding="utf8",
            )
            call("index")
            updated = call("context")
            if before["revision"] == updated["revision"] or not any(
                marker in x["content"] for x in updated["sources"]
            ):
                raise AssertionError("Updated specification was not retrieved")
            result = call("develop")
            resumed = call("resume")
            if (
                not result["actual_minimax"]
                or resumed["checkpoint"]["state"]["status"] != "validated"
            ):
                raise AssertionError("Real MiniMax state not verified")
            if updated["process_id"] == resumed["process_id"]:
                raise AssertionError("State recovery must use a new process")
            if (
                resumed["checkpoint"]["state"]["code_revision"]
                != result["code_revision_after"]
            ):
                raise AssertionError("Recovered state belongs to another revision")
            readiness = {
                "ready_for_review": True,
                "official_submitted": False,
                "scope": "actual MiniMax + seekdb + PowerContext",
                "specification_update_verified": True,
                "separate_process_resume": True,
                "context_module_sha256": hashlib.sha256(
                    (HERE / "sdd_context.py").read_bytes()
                ).hexdigest(),
                "evidence_directory": str(root / "evidence"),
                "run_directory": str(root),
                "versions": {
                    "python": platform.python_version(),
                    **{
                        name: importlib.metadata.version(name)
                        for name in ("httpx", "PyMySQL", "powercontext")
                    },
                },
                "powercontext_source_commit": "fda256c329c6ea9f6e6bb037354922f0f577ac5e",
            }
            (root / "readiness.json").write_text(
                json.dumps(readiness, indent=2), encoding="utf8"
            )
            print(json.dumps(readiness))
    except Exception as error:
        (root / "failed.json").write_text(
            json.dumps({"ready_for_review": False, "error": str(error)}),
            encoding="utf8",
        )
        raise


if __name__ == "__main__":
    main()
