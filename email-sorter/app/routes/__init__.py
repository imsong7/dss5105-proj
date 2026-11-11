"""HTTP routes, one Flask blueprint per area.

    account      /api/session, /api/profile, /api/setup*, /register/connect
    inbound      /api/inbound/*  (Power Automate webhook and refreshes)
    mail         /api/emails, /api/classify, /api/backends, /api/health, ...
    corrections  /api/corrections, /api/sender-rules
    replies      /api/draft-reply, /api/send-reply
    planner      /api/events, /api/item-states, /api/feed*, /feed/*, /api/saved-jobs
"""

from flask import Flask

from app.routes import account, corrections, inbound, mail, planner, replies
from app.routes.common import SorterState

__all__ = ["SorterState", "register_blueprints"]


def register_blueprints(app: Flask) -> None:
    for module in (account, inbound, mail, corrections, replies, planner):
        app.register_blueprint(module.bp)
