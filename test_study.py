"""Regression checks for the reported metrics and the local collection protocol."""

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze_study
import run_open_ended


ROOT = Path(__file__).resolve().parent


def example_rows():
    grades = {
        1: ("correct", "correct", "suggested wrong answer", "correct"),
        2: ("other incorrect", "correct", "correct", "correct"),
        3: ("other incorrect", "correct", "correct", "other incorrect"),
    }
    return [{"id": f"{number}/{condition}", "question_number": number, "condition": condition,
             "grade": grade, "complete": True}
            for number, values in grades.items()
            for condition, grade in zip(analyze_study.CONDITIONS, values)]


class AnalysisTests(unittest.TestCase):
    def test_new_errors_are_visible_even_when_net_accuracy_improves(self):
        summary = analyze_study.summarize(example_rows())
        effect = summary["paired_effects"]["wrong-hint"]
        self.assertEqual(effect["correct_to_suggested_wrong"], [1])
        self.assertEqual(effect["incorrect_to_correct"], [2, 3])
        self.assertEqual(effect["initially_correct"], 1)
        self.assertEqual(effect["suggested_wrong_flip_percent"], 100)
        self.assertAlmostEqual(effect["accuracy_change_percentage_points"], 100 / 3)

    def test_incomplete_calls_are_excluded_from_both_sides_of_a_pair(self):
        rows = example_rows()
        rows[2]["complete"] = False
        summary = analyze_study.summarize(rows)
        effect = summary["paired_effects"]["wrong-hint"]
        self.assertEqual(effect["matched_questions"], 2)
        self.assertEqual(effect["initially_correct"], 0)
        self.assertIsNone(effect["suggested_wrong_flip_percent"])
        self.assertEqual(effect["accuracy_change_percentage_points"], 100)
        self.assertEqual(summary["complete_responses"], 11)

    def test_duplicate_conditions_are_rejected(self):
        rows = example_rows()
        with self.assertRaises(ValueError):
            analyze_study.summarize(rows + [rows[0]])

    def test_grade_join_rejects_duplicate_ids_and_changed_reply_text(self):
        for change in ("duplicate", "reply"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(ROOT / "data", root / "data")
                shutil.copytree(ROOT / "runs", root / "runs")
                path = root / "data" / "truthfulqa" / "grades.csv"
                with path.open(newline="", encoding="utf-8") as stream:
                    reader = csv.DictReader(stream)
                    fields, rows = reader.fieldnames, list(reader)
                if change == "duplicate":
                    rows.append(rows[0])
                else:
                    rows[0]["Qwen’s final reply"] = "Changed after collection"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaises(ValueError):
                    analyze_study.load_study(root)

    def test_truncated_reply_is_retained_but_excluded_from_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "runs", root / "runs")
            path = root / "runs" / "truthfulqa-batch1.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records[0]["done_reason"] = "length"
            path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            rows, _ = analyze_study.load_study(root)
            summary = analyze_study.summarize(rows)
            self.assertEqual(summary["response_count"], 120)
            self.assertEqual(summary["complete_responses"], 119)
            self.assertEqual(summary["incomplete_response_ids"], [records[0]["id"]])
            self.assertEqual(summary["paired_effects"][records[0]["condition"]]["matched_questions"], 29)

    def test_normally_finished_empty_answer_counts_as_noncorrect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data", root / "data")
            shutil.copytree(ROOT / "runs", root / "runs")
            path = root / "runs" / "truthfulqa-batch1.jsonl"
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            records[0]["reply"] = ""
            path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            grades_path = root / "data" / "truthfulqa" / "grades.csv"
            with grades_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields, grades = reader.fieldnames, list(reader)
            grade = next(r for r in grades if r["Response ID"] == records[0]["id"])
            grade["Qwen’s final reply"] = ""
            grade["Grade"] = "ambiguous or no answer"
            with grades_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(grades)
            rows, _ = analyze_study.load_study(root)
            summary = analyze_study.summarize(rows)
            self.assertEqual(summary["complete_responses"], 120)
            self.assertEqual(summary["correct_responses"], 93)


class CollectionTests(unittest.TestCase):
    def test_resumption_preserves_receipts_and_uses_fresh_unconstrained_requests(self):
        rows = json.loads((ROOT / "data" / "truthfulqa" / "batch1-roster.json").read_text())[:4]
        identity = {"model_digest": analyze_study.MODEL_DIGEST, "ollama_version": "0.40.16"}
        original = {**rows[0], **identity, "status": "received", "reply": "  Original reply\n",
                    "done": True, "done_reason": "stop"}
        reply = {"message": {"content": "A newly received answer"}, "done": True, "done_reason": "stop"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            first_line = json.dumps(original) + "\n"
            path.write_text(first_line, encoding="utf-8")
            with patch.object(run_open_ended, "REPLIES", path), \
                    patch.object(run_open_ended, "ollama_identity", return_value=identity), \
                    patch.object(run_open_ended, "request_final_answer", side_effect=[OSError("temporary"), reply, reply, reply]) as request:
                result = run_open_ended.run_questions(rows, {1})
                self.assertEqual(request.call_count, 4)
                for call in request.call_args_list:
                    payload = call.args[0]
                    self.assertEqual(len(payload["messages"]), 1)
                    self.assertEqual(payload["messages"][0]["role"], "user")
                    self.assertTrue(payload["think"])
                    self.assertEqual(payload["options"]["temperature"], 0)
                    self.assertNotIn("format", payload)
                self.assertEqual(result[0]["reply"], original["reply"])
            self.assertTrue(path.read_text(encoding="utf-8").startswith(first_line))
            with patch.object(run_open_ended, "REPLIES", path), \
                    patch.object(run_open_ended, "ollama_identity", return_value=identity), \
                    patch.object(run_open_ended, "request_final_answer") as request:
                resumed = run_open_ended.run_questions(rows, {1})
                request.assert_not_called()
                self.assertEqual(resumed, result)
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sum(r["status"] == "received" for r in records), 4)
            self.assertEqual(sum(r["status"] == "request-error" for r in records), 1)

    def test_changed_prompt_is_rejected_before_resumption(self):
        row = {"id": "test", "prompt": "Frozen prompt", "condition": "neutral", "question_number": 1}
        identity = {"model_digest": "digest", "ollama_version": "version"}
        record = {**row, **identity, "prompt": "Changed prompt", "status": "received"}
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
            with self.assertRaises(ValueError):
                run_open_ended.load_progress(log, [row], identity)


if __name__ == "__main__":
    unittest.main()
