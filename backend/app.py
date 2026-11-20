import logging
import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError(
        "Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in the environment."
    )

supabase: Client = create_client(supabase_url, supabase_key)


@app.after_request
def enable_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def parse_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


@app.get("/")
def index():
    return jsonify({"message": "Events API is running"})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/events")
def list_events():
    try:
        result = supabase.table("events").select("*").execute()
        return jsonify(result.data), 200
    except APIError:
        app.logger.exception("Failed to load events")
        return jsonify({"error": "Could not load events"}), 500


@app.get("/api/events/<event_id>")
def get_event(event_id):
    event_id = parse_uuid(event_id)
    if not event_id:
        return jsonify({"error": "Invalid event ID"}), 400

    try:
        result = (
            supabase.table("events")
            .select("*")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return jsonify({"error": "Event not found"}), 404
        return jsonify(result.data[0]), 200
    except APIError:
        app.logger.exception("Failed to load event")
        return jsonify({"error": "Could not load event"}), 500


@app.post("/api/registrations")
def create_registration():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Request body must be JSON"}), 400

    user_id = parse_uuid(body.get("user_id"))
    event_id = parse_uuid(body.get("event_id"))
    if not user_id or not event_id:
        return jsonify({"error": "Valid user_id and event_id are required"}), 400

    try:
        event_result = (
            supabase.table("events")
            .select("id,capacity")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        if not event_result.data:
            return jsonify({"error": "Event not found"}), 404

        existing = (
            supabase.table("registrations")
            .select("id")
            .eq("user_id", user_id)
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return jsonify({"error": "Already registered"}), 409

        event = event_result.data[0]
        if event.get("capacity") is not None:
            registrations = (
                supabase.table("registrations")
                .select("id", count="exact")
                .eq("event_id", event_id)
                .execute()
            )
            if (registrations.count or 0) >= event["capacity"]:
                return jsonify({"error": "Event is full"}), 409

        result = (
            supabase.table("registrations")
            .insert({"user_id": user_id, "event_id": event_id})
            .execute()
        )
        return jsonify(result.data[0]), 201

    except APIError as error:
        if getattr(error, "code", None) in ("23505", "409"):
            return jsonify({"error": "Already registered"}), 409
        app.logger.exception("Failed to create registration")
        return jsonify({"error": "Could not create registration"}), 500


@app.get("/api/me/registrations")
def get_user_registrations():
    return jsonify({
        "error": "This endpoint requires a verified user identity."
    }), 401


@app.get("/api/events/<event_id>/registrations")
def get_event_registrations(event_id):
    return jsonify({
        "error": "This endpoint requires verified organizer ownership."
    }), 401


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )