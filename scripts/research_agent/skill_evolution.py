"""Bounded Skill evolution CLI; help, validation and reports are network-free."""

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

from deep_research.skill_evolution import (
    Dataset,
    Evidence,
    Manifest,
    revision,
    skill_definition,
)
from deep_research.skill_evolution_runner import (
    analysis,
    candidates,
    capture_configuration,
    collect,
    compare,
    evaluate,
    freeze,
    implementation_versions,
    load_environment,
    report,
)
from deep_research.skill_evolution_store import Store, promote, rollback, safe_error


def parser():
    """Build a parser without environment loading or graph/model imports."""
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("schema", "versions", "config", "register"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--out", type=Path)
        if name == "register":
            cmd.add_argument("--input", type=Path, required=True)
        if name == "schema":
            cmd.add_argument("--kind", choices=("manifest", "evidence", "accounting"), default="manifest")
    init = commands.add_parser("init")
    init.add_argument("--spec", type=Path, required=True)
    init.add_argument("--parent", type=Path, required=True)
    for name in ("validate", "collect", "diagnose", "generate", "run", "compare", "freeze", "report", "promote", "rollback", "account"):
        cmd = commands.add_parser(name)
        if name in {"collect", "account"}:
            cmd.add_argument("--input", type=Path, required=True)
        if name in {"diagnose", "generate", "run"}:
            cmd.add_argument("--allow-external", action="store_true", help="explicitly allow model/search/service calls")
        if name == "run":
            cmd.add_argument("--split", choices=("development", "selection", "final"), required=True)
            cmd.add_argument("--dataset", type=Path, required=True)
        if name in {"compare", "freeze"}:
            cmd.add_argument("--candidate", choices=("1", "2"), required=True)
        if name == "compare":
            cmd.add_argument("--split", choices=("selection", "final"), default="selection")
        if name in {"promote", "rollback"}:
            cmd.add_argument("--production-file", type=Path, required=True)
        if name == "report":
            cmd.add_argument("--out", type=Path, required=True)
    for cmd in commands.choices.values():
        if cmd.prog.split()[-1] not in {"schema", "versions", "config", "register"}:
            cmd.add_argument("--dir", type=Path, required=True, help="explicit experiment directory")
    return root


def main(argv=None):
    """Dispatch only explicitly requested work; never launch a loop."""
    args = parser().parse_args(argv)
    if args.command in {"diagnose", "generate", "run"} and not args.allow_external:
        parser().error("this command requires --allow-external; no calls were made")
    try:
        if args.command == "schema":
            from deep_research.skill_evolution_accounting import Accounting
            value = {"manifest": Manifest, "evidence": Evidence, "accounting": Accounting}[args.kind].model_json_schema()
        elif args.command == "register":
            from deep_research.skill_evolution_runner import Example
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            examples = [Example.model_validate(e) for e in payload["examples"]]
            identities = {e.id: revision({"inputs": e.inputs, "reference_outputs": e.reference_outputs}) for e in examples}
            if len(identities) != len(examples):
                raise ValueError("duplicate example ID")
            value = Dataset(dataset_id=payload["dataset_id"], version=payload["version"], examples=identities).model_dump()
        elif args.command in {"versions", "config"}:
            value = {"versions": implementation_versions, "config": capture_configuration}[args.command]()
        else:
            # Resolve archive paths and credential guards consistently with config.
            # Loading .env does not construct models or import the research graph.
            load_environment()
            store = Store(args.dir)
            value = {"command": args.command, "status": "complete"}
            if args.command == "init":
                spec = Manifest.model_validate_json(args.spec.read_text(encoding="utf-8"))
                from deep_research.run_configuration import validate_snapshot
                validate_snapshot(spec.configuration)
                from deep_research.skill_evolution_runner import verify_implementation
                verify_implementation(spec)
                store.initialize(spec, args.parent.read_text(encoding="utf-8"))
            elif args.command == "validate":
                manifest = store.manifest
                if revision(skill_definition(store.get("parent"))) != manifest.parent_revision:
                    raise ValueError("parent hash mismatch")
                for name in store.names():
                    store.get(name)
            elif args.command == "collect":
                from deep_research.skill_evolution_runner import normalize_export
                payload = json.loads(args.input.read_text(encoding="utf-8"))
                collect(store, normalize_export(store.manifest, payload) if isinstance(payload, dict) else payload)
            elif args.command == "diagnose":
                analysis(store)
            elif args.command == "generate":
                candidates(store)
            elif args.command == "run":
                evaluate(store, args.split, args.dataset)
                from deep_research.skill_evolution_runner import attempts
                rows = [a for a in attempts(store) if a.split == args.split]
                value["complete"] = all(a.status == "complete" and len(a.feedback) == 3 for a in rows)
                value["status"] = "recorded; inspect completeness and unknown accounting"
            elif args.command == "account":
                from deep_research.skill_evolution_accounting import import_accounting
                import_accounting(store, json.loads(args.input.read_text(encoding="utf-8")))
            elif args.command == "compare":
                value = compare(store, args.candidate, args.split).model_dump()
            elif args.command == "freeze":
                freeze(store, args.candidate)
            elif args.command == "report":
                args.out.write_text(report(store), encoding="utf-8")
            elif args.command == "promote":
                frozen = store.get("frozen")
                decision = compare(store, frozen["candidate_id"], "final")
                promote(store, args.production_file, store.get(f"candidate/{frozen['candidate_id']}"), decision.model_dump())
            elif args.command == "rollback":
                rollback(store, args.production_file)
        text = json.dumps(value, ensure_ascii=False, indent=2)
        if args.command in {"schema", "versions", "config", "register"} and args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
        else:
            sys.stdout.write(text + "\n")
        return 0
    except Exception as exc:
        if "store" in locals():
            try:
                store.put(f"command_failed/{uuid.uuid4()}", {"command": args.command, "error": safe_error(exc)})
            except (OSError, ValueError, sqlite3.Error):
                pass
        # ValidationError / provider exceptions may embed inputs and credentials.
        sys.stderr.write("Command failed; no automatic retry. Check sealed inputs and safe ledger diagnostics.\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
