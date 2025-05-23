from a2wsgi import ASGIMiddleware
from app import app # Imports the 'app' instance from your 'app.py'

# This creates an ASGI-compatible application from your Flask app
asgi_app = ASGIMiddleware(app)