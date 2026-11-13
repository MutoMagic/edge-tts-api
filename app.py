import logging
from typing import cast

from flask import Flask
from flask.json.provider import DefaultJSONProvider

from danmaku_api import danmaku_api
from openai_compat import openai_compat

app = Flask(__name__)
cast(DefaultJSONProvider, app.json).ensure_ascii = False
app.logger.setLevel(logging.INFO)
app.register_blueprint(danmaku_api)
app.register_blueprint(openai_compat)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=1234, debug=False)
