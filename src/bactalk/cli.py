from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from bactalk.compiler import NiagaraCompiler
from bactalk.domain import canonical_json
from bactalk.integrations.cxf_importer import CxfImporter
from bactalk.integrations.cxf_vectors import CxfVectorVerifier
from bactalk.library_demo import lbnl_vav_reheat_demo_job
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bactalk", description="BACTalk controls workbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="compile and test the example VAV job")
    demo.add_argument("--output", type=Path, default=Path(".bactalk/runs"))

    serve = subparsers.add_parser("serve", help="run the local review workbench")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--output", type=Path, default=Path(".bactalk/runs"))

    clean = subparsers.add_parser("clean", help="remove generated local runs")
    clean.add_argument("--output", type=Path, default=Path(".bactalk/runs"))

    worker = subparsers.add_parser(
        "qualification-worker",
        help="run the isolated RQ worker for long building-physics qualifications",
    )
    worker.add_argument("--output", type=Path, default=Path(".bactalk/runs"))
    worker.add_argument("--jobs", type=Path, default=Path(".bactalk/qualification-jobs"))
    worker.add_argument("--queue")
    worker.add_argument("--burst", action="store_true")

    translate = subparsers.add_parser(
        "translate-cxf",
        help="lower ASHRAE 231P CXF into typed IR and a Niagara .bog",
    )
    translate.add_argument("source", type=Path)
    translate.add_argument("--vectors", type=Path)
    translate.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "demo":
        service = WorkbenchService(RunRepository(args.output))
        record = service.create_run(lbnl_vav_reheat_demo_job())
        print(json.dumps(record.model_dump(mode="json"), indent=2))
        return
    if args.command == "serve":
        load_dotenv(Path(".env"), override=False)
        import uvicorn

        import bactalk.api

        bactalk.api.app = bactalk.api.create_app(args.output)
        uvicorn.run("bactalk.api:app", host=args.host, port=args.port, reload=args.reload)
        return
    if args.command == "clean":
        RunRepository(args.output).clean()
        print(f"Removed generated runs under {args.output.resolve()}")
        return
    if args.command == "qualification-worker":
        load_dotenv(Path(".env"), override=False)
        from redis import Redis
        from rq import Queue, SpawnWorker
        from rq.serializers import JSONSerializer

        queue_url = os.getenv(
            "BACTALK_QUEUE_URL",
            "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0",
        )
        connection = Redis.from_url(queue_url)
        connection.ping()
        queue_name = args.queue or os.getenv(
            "BACTALK_QUALIFICATION_QUEUE", "bactalk-qualification"
        )
        queue = Queue(queue_name, connection=connection, serializer=JSONSerializer)
        os.environ["BACTALK_RUNS"] = str(args.output.resolve())
        os.environ["BACTALK_QUALIFICATION_JOBS"] = str(args.jobs.resolve())
        worker = SpawnWorker(
            [queue],
            connection=connection,
            serializer=JSONSerializer,
            name=f"bactalk-qualification-{os.getpid()}",
        )
        worker.work(burst=args.burst, logging_level="INFO")
        return
    if args.command == "translate-cxf":
        importer = CxfImporter()
        document = importer.load(args.source)
        graph = importer.import_graph(document)
        args.output.mkdir(parents=True, exist_ok=True)
        graph_path = args.output / f"{graph.name}.control-graph.json"
        bog_path = args.output / f"{graph.name}.bog"
        graph_path.write_text(canonical_json(graph), encoding="utf-8")
        NiagaraCompiler().compile(graph, bog_path)
        vector_report = None
        if args.vectors:
            vectors = json.loads(args.vectors.read_text(encoding="utf-8"))
            vector_report = CxfVectorVerifier().verify(graph, vectors)
            report_path = args.output / f"{graph.name}.vector-report.json"
            report_path.write_text(
                json.dumps(vector_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if not vector_report["passed"]:
                raise SystemExit("CXF vectors failed; generated artifacts are not releasable")
        print(
            json.dumps(
                {
                    "graph": str(graph_path),
                    "bog": str(bog_path),
                    "coverage": graph.metadata["coverage"],
                    "vector_report": vector_report,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
