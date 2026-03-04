from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import requests
import stripe
import os
import redis
import logging
import time
import secrets
import json
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per hour"],
    storage_uri="redis://localhost:6379/0",
    strategy="fixed-window"
)

stripe.api_key = os.getenv('STRIPE_KEY')

try:
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    r.ping()
except:
    r = None
    app.logger.warning("Redis not available, using memory store")

logging.basicConfig(level=logging.INFO)
memory_store = {}

@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    email = data.get('email')
    target_url = data.get('target_url')
    # Ignore password field if present
    
    if not email or not target_url:
        return jsonify({"error": "Email and target_url required"}), 400
    
    try:
        customer = stripe.Customer.create(email=email)
        price_id = "price_1T6io8EJWJEx7oX0FLFRcSLl"
        subscription = stripe.Subscription.create(
            customer=customer.id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"]
        )
        
        api_key = secrets.token_urlsafe(32)
        user_config = {
            'target_url': target_url,
            'subscription_item': subscription['items']['data'][0]['id'],
            'email': email
        }
        
        if r:
            r.set(f"user:{api_key}", json.dumps(user_config))
        else:
            memory_store[api_key] = user_config
        
        return jsonify({
            "api_key": api_key,
            "client_secret": subscription.latest_invoice.payment_intent.client_secret
        })
    except Exception as e:
        app.logger.error(f"Registration error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    redis_status = "connected" if r and r.ping() else "disconnected (using memory)"
    return jsonify({"status": "healthy", "redis": redis_status, "users": len(memory_store) if not r else "unknown"})

@app.route('/convert', methods=['POST'])
@limiter.limit("60 per minute")
def convert_webhook():
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    user_config = None
    if r and r.exists(f"user:{api_key}"):
        user_config = json.loads(r.get(f"user:{api_key}"))
    elif api_key in memory_store:
        user_config = memory_store[api_key]
    
    if not user_config:
        return jsonify({"error": "Invalid API key"}), 401

    try:
        if user_config['subscription_item'] and stripe.api_key.startswith('sk_'):
            stripe.SubscriptionItem.create_usage_record(
                user_config['subscription_item'],
                quantity=1,
                timestamp=int(time.time())
            )

        transformed_data = request.get_json()
        response = requests.post(user_config['target_url'], json=transformed_data, timeout=10)
        app.logger.info(f"Forwarded to {user_config['target_url']}, status {response.status_code}")
        return jsonify({"status": "success", "response_code": response.status_code})
    except Exception as e:
        app.logger.error(f"Error: {str(e)}")
        return jsonify({"error": "Internal error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
