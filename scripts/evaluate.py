#!/usr/bin/env python3
"""Evaluates the knowledge base against eval/questions.jsonl.

For each question it simulates the asking user's Cognito groups with the SAME
filter code the API uses, then measures:

  hit@k      the expected document appears in the top-k retrieved chunks
  leaks      a retrieved chunk the simulated user must not see (should be 0)
  answer     (--generate) expected keywords appear in the generated answer,
             or the refusal phrase appears when no answer should exist

Usage:
  python3 scripts/evaluate.py                # retrieval only (cheap)
  python3 scripts/evaluate.py --generate     # also generates answers
Needs AWS credentials allowed to call bedrock:Retrieve / RetrieveAndGenerate.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from app.access import UserContext, build_retrieval_filter  # noqa: E402
from app.config import Settings  # noqa: E402
from app.rag import build_request, parse_response  # noqa: E402

REFUSAL = "couldn't find this in the documents"


def tf_output(name: str) -> str:
    return subprocess.check_output(
        ["terraform", f"-chdir={ROOT / 'infrastructure' / 'terraform'}", "output", "-raw", name], text=True
    ).strip()


def allowed(user: UserContext, metadata: dict) -> bool:
    if user.is_admin:
        return True
    if metadata.get("department") not in user.departments:
        return False
    return user.can_read_confidential or metadata.get("classification") in {"public", "internal"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="also call RetrieveAndGenerate")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--file", default=str(ROOT / "eval" / "questions.jsonl"))
    args = parser.parse_args()

    region = tf_output("region")
    settings = Settings(
        region=region,
        knowledge_base_id=tf_output("knowledge_base_id"),
        data_source_id=tf_output("data_source_id"),
        model_arn=tf_output("generation_model_arn"),
        rerank_model_arn="",
        guardrail_id="",
        guardrail_version="",
        table_name="",
        docs_bucket=tf_output("docs_bucket"),
        num_results=args.k,
        num_reranked=args.k,
        enable_query_decomposition=False,
        max_question_chars=1000,
        presign_seconds=60,
        history_ttl_days=1,
    )
    client = boto3.client("bedrock-agent-runtime", region_name=region)

    rows, hits, scored, leaks, answers_ok, answers_total = [], 0, 0, 0, 0, 0
    for line in Path(args.file).read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        user = UserContext("eval", groups=frozenset(case["groups"]))
        flt = build_retrieval_filter(user)

        vec = {"numberOfResults": args.k}
        if flt:
            vec["filter"] = flt
        results = client.retrieve(
            knowledgeBaseId=settings.knowledge_base_id,
            retrievalQuery={"text": case["question"]},
            retrievalConfiguration={"vectorSearchConfiguration": vec},
        )["retrievalResults"]

        files = [r["location"]["s3Location"]["uri"].rsplit("/", 1)[-1] for r in results]
        case_leaks = sum(1 for r in results if not allowed(user, r.get("metadata", {})))
        leaks += case_leaks

        hit = None
        if case.get("expected_source"):
            scored += 1
            hit = case["expected_source"] in files
            hits += int(hit)

        answer_ok = None
        if args.generate:
            answers_total += 1
            raw = client.retrieve_and_generate(**build_request(case["question"], flt, settings))
            text = parse_response(raw)["answer"].lower()
            if case.get("should_answer", True):
                answer_ok = all(k.lower() in text for k in case.get("expected_keywords", []))
            else:
                answer_ok = REFUSAL in text
            answers_ok += int(answer_ok)

        rows.append((case["id"], hit, case_leaks, answer_ok, files[:3]))

    print(f"\n{'id':<22}{'hit@' + str(args.k):<8}{'leaks':<7}{'answer':<8}top files")
    for cid, hit, lk, ans, top in rows:
        fmt = lambda v: "-" if v is None else ("yes" if v else "NO")  # noqa: E731
        print(f"{cid:<22}{fmt(hit):<8}{lk:<7}{fmt(ans):<8}{', '.join(top)}")

    print(f"\nRetrieval hit@{args.k}: {hits}/{scored} ({(hits / scored * 100 if scored else 0):.0f}%)")
    print(f"Access-control leaks: {leaks} (must be 0)")
    if args.generate:
        print(f"Answer checks passed: {answers_ok}/{answers_total}")
    sys.exit(1 if leaks else 0)


if __name__ == "__main__":
    main()
