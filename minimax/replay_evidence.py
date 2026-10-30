"""Replay a captured real-model change with identical protected tests, without a new model call."""

from pathlib import Path
import argparse, json, tempfile
from sdd_context import sha, parse_changes, run_tests, write_json


def replay(evidence, output):
    evidence, output = Path(evidence), Path(output)
    ctx = json.loads((evidence / "context.json").read_text(encoding="utf8"))
    record = json.loads((evidence / "model-record.json").read_text(encoding="utf8"))
    if record.get("actual_minimax") is not True or record.get("provider") != "MiniMax":
        raise ValueError("This record is a mock, not MiniMax development evidence")
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="replay-", dir=output)).resolve()
    for source in ctx["sources"]:
        path = (root / source["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source path escape")
        raw = source["content"].encode("utf8")
        if sha(raw) != source["sha256"]:
            raise ValueError("Recorded source hash mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    before = run_tests(root, "target")
    reg_before = run_tests(root, "regression")
    changes = parse_changes(record["response_text"])
    if not set(changes).issubset(set(ctx["task"]["editable_files"])):
        raise ValueError("Protected edit")
    for name, content in changes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Model path escape")
        expected = (evidence / "after" / name).read_bytes()
        if expected != content.encode("utf8"):
            raise ValueError("Model response differs from captured code")
        path.write_bytes(expected)
    after = run_tests(root, "target")
    reg_after = run_tests(root, "regression")
    result = dict(
        passed=before["exit_code"] != 0
        and "FAIL:" in before["output"]
        and "ERROR:" not in before["output"]
        and after["exit_code"]
        == reg_before["exit_code"]
        == reg_after["exit_code"]
        == 0,
        source="captured real MiniMax record; no model call made",
        target_before=before,
        target_after=after,
        regression_before=reg_before,
        regression_after=reg_after,
    )
    write_json(output / "replay.json", result)
    if not result["passed"]:
        raise ValueError("Evidence replay failed")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence", type=Path)
    p.add_argument("--out", type=Path, default=Path("replay-results"))
    a = p.parse_args()
    print(json.dumps(replay(a.evidence, a.out)))
