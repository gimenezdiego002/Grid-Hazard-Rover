"""Explicit token and USD reservations. No hidden pricing catalog or network I/O."""

from decimal import Decimal


class PayloadEstimator:
    def estimate_input_tokens(self, payload):
        value = payload["estimated_input_tokens"]
        if type(value) is not int or value < 0:
            raise ValueError("Invalid internal token estimate")
        return value


class ConservativeUsdMeter:
    name = "usd"
    precheck_is_estimate = True

    @staticmethod
    def _price(payload, input_tokens, output_tokens):
        pricing = payload["pricing"]
        return (Decimal(input_tokens) * Decimal(pricing["input_per_million"])
                + Decimal(output_tokens) * Decimal(pricing["output_per_million"])) / 1_000_000

    def precheck_estimate(self, node_kind, payload):
        if node_kind != "model_call":
            return None
        return self._price(payload, payload["estimated_input_tokens"],
                           payload["max_output_tokens"])

    def charge(self, node_kind, payload, result, meta):
        if node_kind != "model_call":
            return Decimal(0)
        usage = result.get("usage", {}) if isinstance(result, dict) else {}
        values = [usage.get("input_tokens"), usage.get("output_tokens")]
        if any(type(value) is not int or value < 0 for value in values):
            return self.precheck_estimate(node_kind, payload)
        return self._price(payload, *values)
