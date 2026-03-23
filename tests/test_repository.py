import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.adapters.storage import SQLiteRepository
from xhs_downloader.domain.models import (
    DownloadTask,
    JobStatus,
    NoteSummary,
    SearchFilters,
    SearchJob,
    TaskStatus,
)


class RepositoryTests(unittest.TestCase):
    def test_repository_persists_jobs_summaries_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            repository = SQLiteRepository(db_path)
            repository.initialize()

            job = SearchJob(
                run_id="run_1",
                keyword="穿搭",
                pages=3,
                sort="comprehensive",
                filters=SearchFilters(min_likes=100, min_comments=5),
                status=JobStatus.PENDING,
                mode="run",
                created_at="2026-03-23T00:00:00+00:00",
                updated_at="2026-03-23T00:00:00+00:00",
                output_dir="downloads/run_1",
                message="",
            )
            repository.create_job(job)

            summary = NoteSummary(
                note_id="note_1",
                title="春季穿搭",
                author_name="作者A",
                like_count=888,
                comment_count=66,
                note_url="https://example.com/note_1",
                search_rank=1,
            )
            repository.save_note_summary(job.run_id, summary)

            task = DownloadTask(
                task_id="task_1",
                run_id=job.run_id,
                note_id=summary.note_id,
                asset_id="asset_1",
                source_url="https://example.com/1.jpg",
                filename="001.jpg",
                output_dir="downloads/run_1/note_1",
                retry_count=0,
                status=TaskStatus.PENDING,
            )
            repository.save_download_task(task)
            repository.update_download_task(task.task_id, TaskStatus.SUCCESS, local_path="downloads/run_1/note_1/001.jpg")

            saved_job = repository.get_job(job.run_id)
            summaries = repository.list_note_summaries(job.run_id)
            tasks = repository.list_download_tasks(job.run_id)
            stats = repository.get_run_stats(job.run_id)

            self.assertIsNotNone(saved_job)
            self.assertEqual("穿搭", saved_job.keyword)
            self.assertEqual(1, len(summaries))
            self.assertEqual("note_1", summaries[0].note_id)
            self.assertEqual(1, len(tasks))
            self.assertEqual(TaskStatus.SUCCESS, tasks[0].status)
            self.assertEqual(1, stats["summary_count"])
            self.assertEqual(1, stats["download_success"])


if __name__ == "__main__":
    unittest.main()
