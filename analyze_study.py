"""Validate the saved TruthfulQA study and regenerate descriptive results offline."""

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from run_pilot import MODEL_DIGEST


ROOT = Path(__file__).resolve().parent
CONDITIONS = ("neutral", "correct-hint", "wrong-hint", "doubt-correct")
LABELS = {
    "neutral": "No hint",
    "correct-hint": "Suggest the right answer",
    "wrong-hint": "Suggest the wrong answer",
    "doubt-correct": "Doubt the right answer",
}
GRADES = ("correct", "suggested wrong answer", "other incorrect", "ambiguous or no answer")


def load_study(root=ROOT):
    data = root / "data" / "truthfulqa"
    expected = {}
    received = {}
    transport_errors = 0
    for roster_path in sorted(data.glob("batch*-roster.json")):
        batch = roster_path.stem.removesuffix("-roster")
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        manifest = json.loads((data / f"{batch}-questions.json").read_text(encoding="utf-8"))
        questions = {q["question_number"]: q for q in manifest["questions"]}
        for row in roster:
            if row["id"] in expected:
                raise ValueError(f"Duplicate roster ID {row['id']}.")
            question = questions[row["question_number"]]
            if any(row[key] != question[key] for key in ("question", "reference", "distractor")):
                raise ValueError(f"Roster and question bank disagree for {row['id']}.")
            expected[row["id"]] = row
        batch_ids = {r["id"] for r in roster}
        path = root / "runs" / f"truthfulqa-{batch}.jsonl"
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            record = json.loads(line)
            key = record["id"]
            if key not in batch_ids:
                raise ValueError(f"Unexpected ID in {path.name} at line {line_number}.")
            if any(record[field] != expected[key][field] for field in
                   ("prompt", "question_number", "condition", "question", "reference", "distractor")):
                raise ValueError(f"Run and roster disagree for {key}.")
            if record.get("model_digest") != MODEL_DIGEST:
                raise ValueError(f"Unexpected model build for {key}.")
            if record["status"] == "request-error":
                transport_errors += 1
            elif record["status"] == "received":
                if key in received:
                    raise ValueError(f"Duplicate received response {key}.")
                received[key] = record
            else:
                raise ValueError(f"Unknown run status for {key}.")
    if not expected or set(received) != set(expected):
        raise ValueError("Every frozen prompt must have exactly one received response.")

    grades_path = data / "grades.csv"
    with grades_path.open(newline="", encoding="utf-8") as stream:
        grades = list(csv.DictReader(stream))
    seen = set()
    rows = []
    for grade in grades:
        key = grade["Response ID"]
        if key not in expected or key in seen:
            raise ValueError(f"Unexpected or duplicate grading ID {key}.")
        seen.add(key)
        call, reply = expected[key], received[key]
        if grade["Grade"] not in GRADES:
            raise ValueError(f"Missing or invalid grade for {key}.")
        checks = {
            "Exact prompt": call["prompt"], "Reference answers": call["reference"],
            "Planned wrong answer": call["distractor"], "Qwen’s final reply": reply["reply"],
            "Prompt condition": LABELS[call["condition"]],
        }
        if any(grade[column] != value for column, value in checks.items()):
            raise ValueError(f"Grading text differs from the original record for {key}.")
        complete = (reply.get("done") is True and reply.get("done_reason") == "stop"
                    and isinstance(reply["reply"], str))
        rows.append({**call, "grade": grade["Grade"], "complete": complete,
                     "sheet_row": int(grade["sheet_row"]), "reply": reply["reply"]})
    if seen != set(expected):
        raise ValueError("The grading file is missing frozen response IDs.")
    provenance = {
        "grades_sha256": hashlib.sha256(grades_path.read_bytes()).hexdigest(),
        "model_digest": MODEL_DIGEST,
        "ollama_versions": sorted({r["ollama_version"] for r in received.values()}),
        "transport_error_attempts": transport_errors,
    }
    return rows, provenance


def summarize(rows):
    questions = {}
    for row in rows:
        if row["condition"] not in CONDITIONS or row["grade"] not in GRADES:
            raise ValueError("Unknown condition or grade.")
        question = questions.setdefault(row["question_number"], {})
        if row["condition"] in question:
            raise ValueError("A question contains duplicate conditions.")
        question[row["condition"]] = row
    if any(set(question) != set(CONDITIONS) for question in questions.values()):
        raise ValueError("Each question must contain all four conditions.")
    completed = [row for row in rows if row["complete"]]
    grade_counts = Counter(row["grade"] for row in completed)
    metrics = []
    for condition in CONDITIONS:
        counts = Counter(row["grade"] for row in completed if row["condition"] == condition)
        total = sum(counts.values())
        metrics.append({"condition": condition, "label": LABELS[condition],
                        "correct": counts["correct"], "total": total,
                        "accuracy_percent": 100 * counts["correct"] / total if total else None,
                        "grade_counts": {grade: counts[grade] for grade in GRADES}})
    effects = {}
    for condition in CONDITIONS[1:]:
        pairs = [q for q in questions.values() if q["neutral"]["complete"] and q[condition]["complete"]]
        eligible = [q for q in pairs if q["neutral"]["grade"] == "correct"]
        specific = [q["neutral"]["question_number"] for q in eligible
                    if q[condition]["grade"] == "suggested wrong answer"]
        other = [q["neutral"]["question_number"] for q in eligible
                 if q[condition]["grade"] not in ("correct", "suggested wrong answer")]
        rescued = [q["neutral"]["question_number"] for q in pairs
                   if q["neutral"]["grade"] != "correct" and q[condition]["grade"] == "correct"]
        delta = sum(int(q[condition]["grade"] == "correct") - int(q["neutral"]["grade"] == "correct")
                    for q in pairs)
        effects[condition] = {
            "matched_questions": len(pairs), "initially_correct": len(eligible),
            "correct_to_suggested_wrong": sorted(specific), "correct_to_other_error": sorted(other),
            "incorrect_to_correct": sorted(rescued),
            "suggested_wrong_flip_percent": 100 * len(specific) / len(eligible) if eligible else None,
            "accuracy_change_percentage_points": 100 * delta / len(pairs) if pairs else None,
        }
    fully_completed = [q for q in questions.values() if all(q[c]["complete"] for c in CONDITIONS)]
    return {
        "question_count": len(questions), "question_numbers": sorted(questions),
        "response_count": len(rows), "complete_responses": len(completed),
        "incomplete_response_ids": [r["id"] for r in rows if not r["complete"]],
        "correct_responses": grade_counts["correct"],
        "overall_accuracy_percent": 100 * grade_counts["correct"] / len(completed) if completed else None,
        "grade_counts": {grade: grade_counts[grade] for grade in GRADES},
        "condition_results": metrics, "paired_effects": effects,
        "questions_correct_in_all_conditions": sum(all(q[c]["grade"] == "correct" for c in CONDITIONS)
                                                   for q in fully_completed),
        "questions_incorrect_in_all_conditions": sum(all(q[c]["grade"] != "correct" for c in CONDITIONS)
                                                     for q in fully_completed),
    }


def write_results(rows, summary, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (output / "accuracy_by_condition.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("condition", "label", "correct", "total", "accuracy_percent"))
        writer.writeheader()
        for metric in summary["condition_results"]:
            writer.writerow({key: metric[key] for key in writer.fieldnames})
    by_question = {}
    for row in rows:
        by_question.setdefault(row["question_number"], {})[row["condition"]] = row
    fields = ["question_number", "question"]
    for condition in CONDITIONS:
        fields.extend((f"{condition}_id", f"{condition}_grade", f"{condition}_complete"))
    with (output / "paired_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for number, question in sorted(by_question.items()):
            record = {"question_number": number, "question": question["neutral"]["question"]}
            for condition in CONDITIONS:
                record.update({f"{condition}_id": question[condition]["id"],
                               f"{condition}_grade": question[condition]["grade"],
                               f"{condition}_complete": question[condition]["complete"]})
            writer.writerow(record)


def plot_accuracy(summary, output):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = summary["condition_results"]
    if any(metric["total"] == 0 for metric in metrics):
        raise ValueError("Plotting requires at least one complete reply in each condition.")
    labels = ["No hint", "Correct suggestion", "Incorrect suggestion", "Doubt correct answer"]
    fig, axis = plt.subplots(figsize=(8.8, 4.0), layout="constrained")
    positions = list(range(len(metrics)))
    axis.barh(positions, [m["accuracy_percent"] for m in metrics], color="#426b8a", height=0.6)
    axis.set_yticks(positions, labels, fontsize=11)
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.set_xlabel("Correct final replies (%)", fontsize=11)
    axis.set_title("Qwen3 4B accuracy by prompt condition", loc="left", fontsize=15, pad=16)
    axis.set_axisbelow(True)
    axis.grid(axis="x", color="#dddddd", linewidth=0.6)
    for index, metric in enumerate(metrics):
        axis.text(2, index, f"{metric['correct']}/{metric['total']}  ({metric['accuracy_percent']:.1f}%)",
                  color="white", va="center", fontsize=11)
    for spine in ("top", "right", "left"):
        axis.spines[spine].set_visible(False)
    fig.savefig(output / "accuracy_by_condition.png", dpi=200, metadata={"Software": "Matplotlib"})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-plot", action="store_true", help="Regenerate numeric results using the standard library only.")
    args = parser.parse_args()
    rows, provenance = load_study()
    summary = {**summarize(rows), "provenance": provenance}
    output = ROOT / "results" / "truthfulqa"
    write_results(rows, summary, output)
    if not args.no_plot:
        plot_accuracy(summary, output)
    print(f"Validated {summary['response_count']} graded responses across {summary['question_count']} questions.")
    accuracy = summary["overall_accuracy_percent"]
    if accuracy is None:
        print("Accuracy is unavailable because no responses completed normally.")
    else:
        print(f"Correct replies: {summary['correct_responses']}/{summary['complete_responses']} ({accuracy:.1f}%).")


if __name__ == "__main__":
    main()
