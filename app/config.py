import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.database_path = Path(
            os.environ.get("DATABASE_PATH", str(Path.home() / ".quiz-language-learning" / "app.db"))
        )
        self.session_size = int(os.environ.get("SESSION_SIZE", "20"))
        self.seed_csv = Path(os.environ.get("SEED_CSV", "./seed/es_ru_basic.csv"))
        self.seed_dir = Path(os.environ.get("SEED_DIR", "./seed"))

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
