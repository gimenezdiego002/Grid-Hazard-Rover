#!/usr/bin/env python3
"""Report environment presence offline; explicitly opt into metadata checks.

No .env files are loaded. Values, response bodies, and native errors are never
printed. Presence is not proof of a working integration or an active free tier.
"""

import argparse
import json
import os
import re
import socket
import urllib.error
import urllib.request


SERVICES = {
    "gemini": {
        "required": ["GEMINI_API_KEY|GOOGLE_API_KEY", "GEMINI_MODEL", "GEMINI_INPUT_USD_PER_MILLION", "GEMINI_OUTPUT_USD_PER_MILLION"],
        "optional": ["RELAY_ALLOW_LIVE_GEMINI"],
        "note": "Presence does not enable live mode; metadata checks do not validate pricing or generation.",
    },
    "gcp": {
        "required": ["GCP_PROJECT_ID", "GCP_REGION"],
        "optional": ["GOOGLE_APPLICATION_CREDENTIALS"],
        "note": "Project selection, billing, IAM, ADC, and deployment are not verified.",
    },
    "elevenlabs": {
        "required": ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"],
        "optional": ["ELEVENLABS_MODEL_ID", "RELAY_ALLOW_ELEVENLABS"],
        "note": "Metadata check does not synthesize speech or validate the selected voice.",
    },
    "tiger": {
        "required": ["TIGER_DATABASE_URL"],
        "optional": ["TIGER_SSLROOTCERT"],
        "note": "Implemented telemetry adapter requires explicit live=True; this script does not connect or verify its schema.",
    },
    "digitalocean": {
        "required": ["DIGITALOCEAN_ACCESS_TOKEN"],
        "optional": ["RELAY_FLEET_MODE", "RELAY_FLEET_API_TOKEN", "RELAY_FLEET_TTL_SECONDS", "RELAY_FLEET_MAX_EVENTS"],
        "note": "Account token is local-only. Fleet API authentication is separate; metadata does not prove a deployed gateway.",
    },
    "snowflake": {
        "required": ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_TOKEN", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA", "SNOWFLAKE_WAREHOUSE"],
        "optional": ["SNOWFLAKE_ROLE", "SNOWFLAKE_TOKEN_TYPE"],
        "note": "SQL API adapter uses an existing warehouse and RELAY_REFERENCES table; this script executes no SQL.",
    },
    "mongodb": {
        "required": ["POLLARD_MONGODB_URI|MONGODB_URI"],
        "optional": ["MONGODB_DATABASE", "POLLARD_MONGODB_DATABASE", "POLLARD_MONGODB_PREFIX", "POLLARD_STORE_ID"],
        "note": "Presence only; Atlas deployment and persistence are unverified. Pollard uses POLLARD_MONGODB_URI.",
    },
    "solana": {
        "required": [],
        "optional": ["RELAY_ALLOW_SOLANA_DEVNET"],
        "fixed_configuration": "fixed_public_devnet_endpoint",
        "note": "RPC is fixed to public devnet. Wallet/funds are not inspected; health checks send no transaction or airdrop.",
    },
    "godaddy": {
        "required": ["GODADDY_DOMAIN"],
        "optional": [],
        "note": "DNS lookup does not verify ownership, eligibility, registration, or HTTPS.",
    },
}

CHECKABLE = ("gemini", "elevenlabs", "digitalocean", "solana", "godaddy")


def value(names):
    return next((os.environ[name].strip() for name in names.split("|")
                 if os.environ.get(name, "").strip()), "")


def configuration():
    result = {}
    for service, spec in SERVICES.items():
        required = {name: bool(value(name)) for name in spec["required"]}
        optional = {name: bool(value(name)) for name in spec["optional"]}
        result[service] = {
            "required_presence": required,
            "optional_presence": optional,
            "configuration": spec.get("fixed_configuration") or ("present_unverified" if all(required.values()) else "incomplete"),
            "connectivity": "not_checked",
            "integration": "not_verified_by_this_script",
            "note": spec["note"],
        }
    mongo_aliases = [value("POLLARD_MONGODB_URI"), value("MONGODB_URI")]
    if all(mongo_aliases) and mongo_aliases[0] != mongo_aliases[1]:
        result["mongodb"]["configuration"] = "conflicting_uri_aliases"
    return result


class NoRedirects(urllib.request.HTTPRedirectHandler):
    # Do not forward an authorization header to an unexpected redirect host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_metadata(url, *, headers=None, data=None):
    request = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.build_opener(NoRedirects()).open(request, timeout=10) as response:
        body = response.read(64_000)
        return response.status, body


def check_network(service):
    """Only this function performs network I/O, after an explicit --check."""
    if service == "gemini":
        if not value("GEMINI_API_KEY|GOOGLE_API_KEY"):
            return "skipped_missing_credential"
        request_metadata("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                         headers={"x-goog-api-key": value("GEMINI_API_KEY|GOOGLE_API_KEY")})
        return "metadata_endpoint_reachable"
    if service == "elevenlabs":
        if not value("ELEVENLABS_API_KEY"):
            return "skipped_missing_credential"
        request_metadata("https://api.elevenlabs.io/v1/user",
                         headers={"xi-api-key": value("ELEVENLABS_API_KEY")})
        return "metadata_endpoint_reachable"
    if service == "digitalocean":
        if not value("DIGITALOCEAN_ACCESS_TOKEN"):
            return "skipped_missing_credential"
        request_metadata("https://api.digitalocean.com/v2/account",
                         headers={"Authorization": "Bearer " + value("DIGITALOCEAN_ACCESS_TOKEN")})
        return "metadata_endpoint_reachable"
    if service == "solana":
        _, body = request_metadata("https://api.devnet.solana.com", headers={"Content-Type": "application/json"},
                                   data=b'{"jsonrpc":"2.0","id":1,"method":"getHealth"}')
        return "devnet_healthy" if json.loads(body).get("result") == "ok" else "devnet_health_not_ok"
    if service == "godaddy":
        domain = value("GODADDY_DOMAIN")
        if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain):
            return "skipped_requires_plain_domain_name"
        socket.getaddrinfo(domain, 443)
        return "dns_resolves"
    raise ValueError("Unsupported explicit check")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print presence and status as JSON; never secret values.")
    parser.add_argument("--check", action="append", choices=CHECKABLE, default=[],
                        help="Opt into one read-only metadata/DNS network check; repeat for specific services.")
    args = parser.parse_args(argv)
    services = configuration()
    failed = False
    for service in dict.fromkeys(args.check):
        try:
            status = check_network(service)
        except urllib.error.HTTPError as error:
            status = f"http_status_{error.code}"
        except Exception:
            # Native error messages and response bodies can contain credentials.
            status = "network_or_response_error"
        services[service]["connectivity"] = status
        if status not in {"metadata_endpoint_reachable", "devnet_healthy", "dns_resolves"}:
            failed = True
    report = {
        "mode": "explicit_network_checks" if args.check else "offline_presence_only",
        "services": services,
        "budget_note": "This check does not validate credits or enforce the $20 cumulative spending limit.",
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Mode:", report["mode"])
        for name, service in services.items():
            print(f"{name}: config={service['configuration']}; connectivity={service['connectivity']}; integration=unverified")
            for env_name, present in service["required_presence"].items():
                print(f"  {env_name}: {'set' if present else 'missing'}")
            print("  " + service["note"])
        print(report["budget_note"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
