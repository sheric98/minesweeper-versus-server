import os

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from flask_cors import CORS
from config import CORS_ORIGINS, DATABASE_URL


def create_app():
    app = Flask(__name__)
    CORS(app, origins=CORS_ORIGINS)

    if DATABASE_URL:
        from db import init_db
        init_db()

    from auth import auth_bp
    from ws_ticket import ws_ticket_bp
    from matchmaking import matchmaking_bp
    from leaderboard import leaderboard_bp
    from head_to_head import head_to_head_bp
    from board_endpoint import board_bp
    from elo_endpoints import elo_bp
    from matchmaking_queue import queue_bp
    from websocket_handler import sock

    app.register_blueprint(auth_bp)
    app.register_blueprint(ws_ticket_bp)
    app.register_blueprint(matchmaking_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(head_to_head_bp)
    app.register_blueprint(board_bp)
    app.register_blueprint(elo_bp)
    app.register_blueprint(queue_bp)
    sock.init_app(app)

    if DATABASE_URL:
        from board_replenisher import start_replenisher
        start_replenisher()

    from matchmaking_queue import start_matchmaking_loop
    start_matchmaking_loop()

    if os.getenv("BOTS_ENABLED") == "1":
        from bots.registry import bot_registry
        bot_registry.load()
        from bots.lifecycle import start_lifecycle_loops
        start_lifecycle_loops()
        from bots.queue_injector import start_queue_injector
        start_queue_injector()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
