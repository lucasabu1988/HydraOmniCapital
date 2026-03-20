import pytest
from flask import Flask


class TestDashAppMounts:
    def test_create_analytics_app_returns_dash(self):
        from compass_analytics import create_analytics_app
        flask_app = Flask(__name__)
        dash_app = create_analytics_app(flask_app)
        assert dash_app is not None

    def test_analytics_route_returns_200(self):
        from compass_analytics import create_analytics_app
        flask_app = Flask(__name__)
        create_analytics_app(flask_app)
        client = flask_app.test_client()
        response = client.get("/analytics/")
        assert response.status_code == 200

    def test_tabs_present_in_layout(self):
        from compass_analytics import create_analytics_app
        flask_app = Flask(__name__)
        dash_app = create_analytics_app(flask_app)
        layout_str = str(dash_app.layout)
        assert "Tearsheet" in layout_str or "tearsheet" in layout_str
        assert "Weight" in layout_str or "weight" in layout_str
