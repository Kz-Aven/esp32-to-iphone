import logging
import os

import uvicorn

debug = os.environ.get("HIDAGENT_DEBUG") == "1"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("hidagent").setLevel(logging.DEBUG if debug else logging.INFO)
uvicorn.run("hidagent.app:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8890)))
