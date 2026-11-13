from __future__ import annotations

import json
import os
from pathlib import Path

from .auth import Auth
from .alegra import AlegraActivators
from .config import RuntimeConfig
from .database import Database
from .ledger import Archive, Ledger


class Application:
    def __init__(self, root: Path, *, database=None, sources=None, background=True):
        self.db = database or Database.from_env()
        self.db.initialize()
        self.auth = Auth(self.db)
        self.alegra = AlegraActivators(self.db)
        self.auth.bootstrap(os.getenv("SIESA_BOOTSTRAP_ADMIN_EMAIL", ""), os.getenv("SIESA_BOOTSTRAP_ADMIN_PASSWORD_HASH", ""))
        if os.getenv("SIESA_ADMIN_PASSWORD_RESET_HASH"):
            self.auth.reset_password(os.getenv("SIESA_BOOTSTRAP_ADMIN_EMAIL", "admin"), os.environ["SIESA_ADMIN_PASSWORD_RESET_HASH"])
        if not self.auth.has_users():
            raise ValueError("Configura la cuenta inicial antes de iniciar el servicio")
        self.ledger = Ledger(self.db)
        runtime = RuntimeConfig.from_env()
        if sources is None:
            definitions = json.loads((root / "config/siesa_activators.json").read_text(encoding="utf-8"))["activators"]
            sources = []
            for activator in definitions:
                for path, kind in ((runtime.log_file, "audit"), (runtime.state_file, "state")):
                    candidate = path if activator == "alianza" else path.with_name(f"{path.stem}_{activator}{path.suffix}")
                    sources.append((candidate, activator, kind))
        self.archive = Archive(self.db, sources, runtime.state_file.parent / "history_migration_backups")
        self.archive.refresh()
        if background:
            self.archive.start()
