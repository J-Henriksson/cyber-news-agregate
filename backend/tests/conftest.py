"""No network, no model, no poller, and a store and profile of the test's own."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="radar-test-")
os.environ["RADAR_NO_DOTENV"] = "1"
os.environ["RADAR_POLL"] = "0"
os.environ["RADAR_DATA"] = _tmp
os.environ["RADAR_PROFILE"] = os.path.join(_tmp, "profile.json")
os.environ["GEMINI_API_KEY"] = ""
