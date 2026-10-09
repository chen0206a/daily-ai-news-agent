import uuid
import pytest
from app.config import Settings
from app.db import Database, dumps, utcnow
from app.schemas import Preferences
from app.services.delivery import DeliveryService
from app.tools.registry import ToolContext, ToolRegistry


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, scheduler_enabled=False, deepseek_api_key="test-only",
                        smtp_host="", smtp_user="", smtp_password="", smtp_from="")
    db = Database(settings.db_path)
    db.initialize()
    user_id, run_id = uuid.uuid4().hex, uuid.uuid4().hex
    prefs = Preferences()
    db.execute("INSERT INTO users VALUES(?,?,?,?)", (user_id, "test@example.com", "unused", utcnow()))
    db.execute("INSERT INTO preferences VALUES(?,?,?)", (user_id, prefs.model_dump_json(), utcnow()))
    db.execute("INSERT INTO runs(id,user_id,status,trigger,slot,preferences,created_at,model) VALUES(?,?,?,?,?,?,?,?)",
               (run_id, user_id, "running", "test", "test", dumps(prefs.model_dump()), utcnow(), "scripted-test-double"))
    ctx = ToolContext(user_id, run_id, prefs, db, settings, None, DeliveryService(db, settings))
    return ctx, ToolRegistry(ctx)
