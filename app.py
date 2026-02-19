import os
import base64
import requests
import secrets

from flask import Flask, request, redirect, jsonify, session
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
ENVIRONMENT = os.getenv("ENVIRONMENT")

# Production vs Sandbox API URL
if ENVIRONMENT == "sandbox":
    BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
else:
    BASE_URL = "https://quickbooks.api.intuit.com"

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

# Temporary in-memory storage
tokens = {}

# ===============================
# LOGIN
# ===============================
@app.route("/login")
def login():

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    auth_url = (
        "https://appcenter.intuit.com/connect/oauth2?"
        f"client_id={CLIENT_ID}"
        "&response_type=code"
        "&scope=com.intuit.quickbooks.accounting"
        f"&redirect_uri={REDIRECT_URI}"
        f"&state={state}"
    )

    return redirect(auth_url)

# ===============================
# CALLBACK
# ===============================
@app.route("/callback")
def callback():

    if request.args.get("state") != session.get("oauth_state"):
        return "Invalid state parameter", 400

    auth_code = request.args.get("code")

    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    token_data = response.json()

    if "access_token" not in token_data:
        return jsonify(token_data), 400

    tokens["access_token"] = token_data["access_token"]
    tokens["refresh_token"] = token_data["refresh_token"]
    tokens["realm_id"] = request.args.get("realmId")

    return jsonify({"message": "Login successful"})

# ===============================
# REFRESH TOKEN
# ===============================
def refresh_access_token():

    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": tokens.get("refresh_token")
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    new_tokens = response.json()

    tokens["access_token"] = new_tokens.get("access_token")
    tokens["refresh_token"] = new_tokens.get("refresh_token")

# ===============================
# OPEN PURCHASE ORDERS DASHBOARD
# ===============================
@app.route("/open-pos")
def get_open_pos():

    access_token = tokens.get("access_token")
    realm_id = tokens.get("realm_id")

    if not access_token:
        return "Not authenticated. Please login.", 401

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    query = "SELECT * FROM PurchaseOrder MAXRESULTS 100"
    url = f"{BASE_URL}/v3/company/{realm_id}/query"

    response = requests.get(
        url,
        headers=headers,
        params={"query": query},
        timeout=10
    )

    # Auto refresh if expired
    if response.status_code == 401:
        refresh_access_token()
        return get_open_pos()

    data = response.json()
    pos = data.get("QueryResponse", {}).get("PurchaseOrder", [])

    open_pos = [po for po in pos if po.get("POStatus") == "Open"]

    # Build simple HTML table
    html = """
    <h1>Open Purchase Orders</h1>
    <table border="1" cellpadding="8">
        <tr>
            <th>PO #</th>
            <th>Vendor</th>
            <th>Date</th>
            <th>Total</th>
        </tr>
    """

    for po in open_pos:
        html += f"""
        <tr>
            <td>{po.get('DocNumber')}</td>
            <td>{po.get('VendorRef', {}).get('name')}</td>
            <td>{po.get('TxnDate')}</td>
            <td>${po.get('TotalAmt')}</td>
        </tr>
        """

    html += "</table>"

    return html

# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)

