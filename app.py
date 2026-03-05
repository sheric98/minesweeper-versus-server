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
    from websocket_handler import sock

    app.register_blueprint(auth_bp)
    app.register_blueprint(ws_ticket_bp)
    app.register_blueprint(matchmaking_bp)
    app.register_blueprint(leaderboard_bp)
    sock.init_app(app)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
