"""DB 초기화 스크립트"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from branding.config import get_settings
from branding.db import init_db

settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db(settings.db_path)
print(f"✓ DB 초기화 완료: {settings.db_path}")
