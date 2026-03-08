import requests
import logging
from flask import Flask, jsonify, request as flask_request, Response

logger = logging.getLogger(__name__)

TIMEOUT = 5


def build_routes(app: Flask, device: dict) -> list[str]:
    """
    Dynamically add Flask routes that proxy to a device's endpoints.
    Reads the device's docs to know what routes to create.
    Returns list of route paths that were added.
    """
    docs = device.get("docs", {})
    endpoints = docs.get("endpoints", [])
    base_url = device["base_url"]
    ip = device["ip"]

    # Use a safe prefix so device routes don't collide with each other or core routes
    # e.g. /device/192.168.137.52/capture
    prefix = f"/device/{ip}"
    added = []

    # Track existing rules to avoid duplicates
    existing_rules = {rule.rule for rule in app.url_map.iter_rules()}

    for ep in endpoints:
        path = ep.get("path", "")
        method = ep.get("method", "GET").upper()
        description = ep.get("description", "")

        if not path or path == "/docs":
            continue

        route_path = f"{prefix}{path}"
        if route_path in existing_rules:
            logger.info(f"Route already exists, skipping: {route_path}")
            continue

        # Build the proxy function for this endpoint
        _create_proxy_route(app, route_path, method, base_url, path, description)
        added.append({"path": route_path, "method": method, "description": description})
        logger.info(f"Added route: {method} {route_path} -> {base_url}{path}")

    return added


def _create_proxy_route(app: Flask, route_path: str, method: str,
                        base_url: str, device_path: str, description: str):
    """Create a single proxy route that forwards requests to the device."""

    # Each route needs a unique function name for Flask
    func_name = f"proxy_{route_path.replace('/', '_').replace('.', '_')}"

    def proxy_handler(**kwargs):
        target_url = f"{base_url}{device_path}"

        # Forward query params
        params = dict(flask_request.args)

        try:
            if method == "GET":
                resp = requests.get(target_url, params=params, timeout=TIMEOUT, stream=True)
            elif method == "POST":
                body = flask_request.get_json(silent=True)
                resp = requests.post(target_url, params=params, json=body, timeout=TIMEOUT)
            elif method == "PUT":
                body = flask_request.get_json(silent=True)
                resp = requests.put(target_url, params=params, json=body, timeout=TIMEOUT)
            elif method == "DELETE":
                resp = requests.delete(target_url, params=params, timeout=TIMEOUT)
            else:
                return jsonify({"error": f"Unsupported method: {method}"}), 400

            content_type = resp.headers.get("Content-Type", "application/json")

            # Stream binary responses (images, mjpeg, audio)
            if "image" in content_type or "multipart" in content_type or "audio" in content_type:
                return Response(resp.content, mimetype=content_type)

            # Try to return JSON, fall back to raw text
            try:
                return jsonify(resp.json()), resp.status_code
            except ValueError:
                return Response(resp.text, status=resp.status_code, mimetype=content_type)

        except requests.exceptions.RequestException as e:
            logger.warning(f"Proxy to {target_url} failed: {e}")
            return jsonify({"error": f"Device unreachable: {e}"}), 503

    # Flask requires unique endpoint names
    proxy_handler.__name__ = func_name
    app.add_url_rule(route_path, func_name, proxy_handler, methods=[method])


def build_all_routes(app: Flask, registry) -> list[dict]:
    """Build proxy routes for all registered devices."""
    all_added = []
    for ip, device in registry.list_devices().items():
        routes = build_routes(app, device)
        if routes:
            all_added.append({"ip": ip, "routes": routes})
    return all_added
