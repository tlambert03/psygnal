# copy_files_hook.py
import shutil
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CopyFilesHook(BuildHookInterface):
    def initialize(self, version: Any, build_data: Any) -> None:
        # Define the source and destination paths
        src_folder = Path("src/psygnal/uncompiled")
        dest_folder = Path("src/psygnal/compiled")

        # Perform the copy operation
        if src_folder.exists():
            for file in src_folder.iterdir():
                if file.is_file():
                    shutil.copy(file, dest_folder)

    def finalize(
        self, version: str, build_data: dict[str, Any], artifact_path: str
    ) -> None:
        for file in Path("src/psygnal/compiled").glob("*.py"):
            if file.is_file():
                file.unlink()
        return super().finalize(version, build_data, artifact_path)
