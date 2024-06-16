"""
Simple script to generate an access token for the user created in the create script.
Opens the browser to log in at Cognito. Make sure to inspect the PASSWORD environment variable first.
Sets a redirect uri to localhost:8083/callback.
At the same time starts a simple webserver listening on localhost:8083/callback for the authorization code
redirect from Cognito.

"""

import json
import webbrowser
import logging
import requests
import jwt
from rich import print
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from requests_oauthlib import OAuth2Session


logging.getLogger().handlers.clear()
logger = logging.getLogger("requests_oauthlib.oauth2_session")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def load_state_from_file():
    with open("state.json", "r") as f:
        return json.load(f)


state = load_state_from_file()


# Change for different results
SCOPES = state["terminal_app_scopes"]  # Authorized
# SCOPES = ["HelloAPI/hello.read", "HelloAPI/hello.write"]  # Authorized
# SCOPES = ["HelloAPI/hello.read"]  # Authorized
# SCOPES = ["openid", "email", "profile", "HelloAPI/hello.read"]  # Authorized
# SCOPES = [state["terminal_app_scopes"][-1]]  # Authorized
# SCOPES = [state["terminal_app_scopes"][-2]]  # Authorized
# SCOPES = ["openid"]  # Unauthorized

# assumes localhost callback as first callback url
callback_url = urlparse(state["terminal_app_callback_urls"][0])
REDIRECT_URL_PORT = callback_url.port
REDIRECT_URL_HOST = callback_url.hostname


redirect_uri = state["terminal_app_callback_urls"][0]
oauth = OAuth2Session(
    client_id=state["terminal_app_client_id"],
    scope=SCOPES,
    redirect_uri=redirect_uri,
    pkce="S256",
)

token_url = f"https://{state['user_pool_auth_domain_prefix']}.auth.us-east-1.amazoncognito.com/oauth2/token"
client_id = state["terminal_app_client_id"]


def decode_token(token):
    jwk_url = f"{state['user_pool_jwt_issuer_url']}/.well-known/jwks.json"
    terminal_app_client_id = state["terminal_app_client_id"]

    jwk_client = jwt.PyJWKClient(jwk_url)
    signing_key = jwk_client.get_signing_key_from_jwt(token)

    # Decode and validate the JWT
    # Disable automatic audience verification
    # cognito encodes aud claim as client_id
    decoded_token = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=terminal_app_client_id,
        options={"verify_aud": False},
    )
    return decoded_token


def verify_token(decoded_token):
    terminal_app_client_id = state["terminal_app_client_id"]
    # Manually verify the client_id
    aud = (
        decoded_token["client_id"]
        if "client_id" in decoded_token
        else decoded_token["aud"]
    )
    if aud != terminal_app_client_id:
        raise Exception("Invalid client_id or aud claim")


def print_token(token):
    if token is None:
        return
    decoded_token = decode_token(token)
    print(token)
    print(decoded_token)
    try:
        verify_token(decoded_token)
    except Exception as e:
        print(e.message)


# Set up a temporary HTTP server to handle the authorization code callback
class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/callback":
            # Extract the authorization code from the URL
            query = parse_qs(parsed_path.query)
            if "code" in query:
                # Respond to the browser
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                    <html>
                    <body>
                    <p>Authorization successful. You can close this window and return to your application.</p>
                    </body>
                    </html>
                """)
                authorization_code = query["code"][0]
                print(f"Authorization code received: {authorization_code}\n")

                print("Get id, access, and refresh tokens")
                token = oauth.fetch_token(
                    token_url,
                    code=authorization_code,
                    client_id=client_id,
                    include_client_id=True,
                    client_secret=None,
                )
                print(token)
                access_token = token.get("access_token", None)
                id_token = token.get("id_token", None)
                refresh_token = token.get("refresh_token", None)

                print()
                print("Tokens")
                print(80 * "-")
                print("ID token")
                print_token(id_token)
                print()
                print("Access token")
                print_token(access_token)
                print()
                print("Refresh token")
                print(refresh_token)
                print()
                print(80 * "-")
                print(
                    "Performing the following authorized request against the API Gateway."
                )
                print(
                    f'curl -H "Authorization: Bearer {token["access_token"]}" {state["api_url"]}\n'
                )
                resp = requests.get(
                    state["api_url"],
                    headers={"Authorization": f"Bearer {token['access_token']}"},
                )
                print(
                    f"Request received '{resp.status_code}' response with body: '{resp.text}'"
                )

            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization code not found in the callback URL.")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")


def main():
    with HTTPServer((REDIRECT_URL_HOST, REDIRECT_URL_PORT), CallbackHandler) as httpd:
        print(f"Serving at {redirect_uri}\n")

        # Generate authorization URL and open in the default web browser
        # /signup for sign up
        authorization_url = state["user_pool_auth_domain"] + "/login"
        auth_url, _ = oauth.authorization_url(authorization_url)
        print(f"Opening login page to obtain an authorization token: {auth_url}\n")
        webbrowser.open(auth_url)

        # Step 7: Wait for the callback to receive the authorization code
        httpd.handle_request()


if __name__ == "__main__":
    main()
