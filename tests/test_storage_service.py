from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_app.services.storage_service import StorageService


class StorageServiceArchiveMediaTests(unittest.TestCase):
    def test_archive_lists_mp4_ts_and_m4a_but_hides_recording_temps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            archive = root / "archive"
            archive.mkdir()
            for name in (
                "video_tn_20260609120000.mp4",
                "video_tn_20260609120000.ts",
                "video_tn_20260609120000.audio.m4a",
                "video_tn_20260609120000.recording.mp4",
                "video_tn_20260609120000.recording.ts",
                "video_tn_20260609120000.recording.m4a",
                "notes.txt",
            ):
                (archive / name).write_bytes(b"x")

            service = StorageService(root, archive)
            files = {item["name"] for item in service.snapshot()["archive"]["latest_files"]}

            self.assertEqual(
                files,
                {
                    "video_tn_20260609120000.mp4",
                    "video_tn_20260609120000.ts",
                    "video_tn_20260609120000.audio.m4a",
                },
            )
            self.assertEqual(service.media_type_for(archive / "video_tn_20260609120000.audio.m4a"), "audio/mp4")


if __name__ == "__main__":
    unittest.main()
