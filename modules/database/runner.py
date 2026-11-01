from __future__ import annotations

import json
import logging
from pathlib import Path

from modules.database.connection import DatabaseConnectionFactory
from modules.database.csv_loader import CsvDatabaseLoader, CsvDefinition


class DatabaseRunner:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.settings_file = (
            self.project_root / "configs" / "database" / "settings.json"
        )
        self.settings = self._load_json(self.settings_file)
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self, action, source_name=None):
        action = str(action).strip().lower()
        if action not in {"init", "load"}:
            raise ValueError("Database action must be init or load")

        sources = self._load_sources()
        if source_name:
            sources = [source for source in sources if source.name == source_name]
        if not sources:
            raise ValueError("No matching database sources")

        completed = []
        failed = []

        with DatabaseConnectionFactory.connect() as connection:
            loader = CsvDatabaseLoader(
                connection=connection,
                project_root=self.project_root,
                schema_name=self.settings.get("schema", "Service"),
            )

            print("[DATABASE] Action={} | Sources={}".format(action, len(sources)))

            for index, source in enumerate(sources, start=1):
                print(
                    "[DATABASE] Running {}/{} | {} | {}".format(
                        index,
                        len(sources),
                        source.name,
                        source.table_name,
                    )
                )

                try:
                    result = (
                        loader.initialize_table(source)
                        if action == "init"
                        else loader.load_table(source)
                    )
                    completed.append(result)
                    print(
                        "[DATABASE COMPLETED] {} | {} | {}".format(
                            source.name,
                            result["status"],
                            source.table_name,
                        )
                    )
                except Exception as error:
                    connection.rollback()
                    failed.append(
                        {
                            "source": source.name,
                            "table": source.table_name,
                            "error_type": type(error).__name__,
                            "error": str(error),
                        }
                    )
                    self.logger.exception(
                        "Database source failed | source=%s",
                        source.name,
                    )
                    print(
                        "[DATABASE FAILED] {} | {}: {}".format(
                            source.name,
                            type(error).__name__,
                            error,
                        )
                    )
                    if not self.settings.get("continue_on_error", True):
                        raise

        print("\n================================")
        print("DATABASE SUMMARY")
        print("================================")
        print("Completed: {}".format(len(completed)))
        print("Failed: {}".format(len(failed)))
        print("================================")

        return {"completed": completed, "failed": failed}

    def _load_sources(self):
        source_directory = (
            self.project_root
            / self.settings.get(
                "source_directory",
                "configs/database/sources",
            )
        ).resolve()

        if not source_directory.exists():
            raise FileNotFoundError(
                "Config directory not found: {}".format(source_directory)
            )

        definitions = []
        for config_file in sorted(source_directory.glob("*.json")):
            data = self._load_json(config_file)
            definition = CsvDefinition(
                name=str(data["name"]).strip(),
                table_name=str(data["table_name"]).strip(),
                file_pattern=str(data["file_pattern"]).strip(),
                enabled=bool(data.get("enabled", True)),
                recursive=bool(data.get("recursive", True)),
            )
            if definition.enabled:
                definitions.append(definition)

        return sorted(definitions, key=lambda item: item.name)

    @staticmethod
    def _load_json(path):
        if not path.exists():
            raise FileNotFoundError("Config not found: {}".format(path))
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise ValueError(
                "Invalid JSON | file={} | line={} | column={} | error={}".format(
                    path,
                    error.lineno,
                    error.colno,
                    error.msg,
                )
            ) from error
        if not isinstance(data, dict):
            raise ValueError("Config must be a JSON object: {}".format(path))
        return data
