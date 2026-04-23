from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from polymarket_trader.config import Settings
from polymarket_trader.domain.order import OrderResultStatus, OrderSide, OrderType
from polymarket_trader.infra.polymarket.order_execution_types import (
    OrderExecutionRequest,
    OrderExecutionResponse,
)


def _text(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text)


def _json_body(value: Any | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


_FIXED_6_UNITS = Decimal("1000000")


def _fixed_6_decimal(value: Any | None) -> Decimal | None:
    amount = _decimal(value)
    if amount is None:
        return None
    return amount / _FIXED_6_UNITS


def _order_type_text(order_type: OrderType | str | None) -> str:
    if isinstance(order_type, OrderType):
        return order_type.value
    text = _text(order_type)
    return text or OrderType.GTC.value


def _is_market_order_type(order_type: OrderType | str | None) -> bool:
    return _order_type_text(order_type).upper() in {"FAK", "FOK"}


def _is_limit_order_type(order_type: OrderType | str | None) -> bool:
    return _order_type_text(order_type).upper() in {"GTC", "GTD"}


def _require_py_clob_client() -> dict[str, Any]:
    proxy_keys = (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
    )
    saved_proxy_env: dict[str, str] = {}
    for key in proxy_keys:
        value = os.environ.get(key)
        if value and value.startswith("socks://"):
            saved_proxy_env[key] = value
            os.environ.pop(key, None)
    try:
        from py_clob_client.client import ClobClient as OfficialClobClient
        from py_clob_client.clob_types import (
            ApiCreds,
            MarketOrderArgs,
            OrderArgs,
            OrderType as OfficialOrderType,
            RequestArgs,
        )
        from py_clob_client.headers.headers import create_level_2_headers
    except ImportError as exc:
        raise RuntimeError(
            "py-clob-client is required for production Polymarket authentication. "
            "Install project dependencies before enabling live trading."
        ) from exc
    finally:
        for key, value in saved_proxy_env.items():
            os.environ[key] = value
    return {
        "client": OfficialClobClient,
        "api_creds": ApiCreds,
        "market_order_args": MarketOrderArgs,
        "order_args": OrderArgs,
        "order_type": OfficialOrderType,
        "request_args": RequestArgs,
        "create_level_2_headers": create_level_2_headers,
    }


@dataclass(frozen=True, slots=True)
class PolymarketCredentials:
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    wallet_private_key: str
    signer_private_key: str | None = None
    chain_id: int = 137
    signature_type: int = 0
    funder_address: str | None = None

    @property
    def signing_private_key(self) -> str:
        return self.signer_private_key or self.wallet_private_key

    @property
    def has_api_credentials(self) -> bool:
        return all((self.api_key, self.api_secret, self.api_passphrase))

    @classmethod
    def from_settings(cls, settings: Settings) -> "PolymarketCredentials | None":
        wallet_private_key = settings._secret_value(settings.wallet_private_key)
        if not wallet_private_key:
            return None
        api_key = settings._secret_value(settings.polymarket_api_key) or None
        api_secret = settings._secret_value(settings.polymarket_api_secret) or None
        api_passphrase = settings._secret_value(settings.polymarket_api_passphrase) or None
        signer_private_key = settings._secret_value(settings.signer_private_key) or None
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
            wallet_private_key=wallet_private_key,
            signer_private_key=signer_private_key,
            chain_id=settings.polymarket_chain_id,
            signature_type=settings.polymarket_signature_type,
            funder_address=settings.polymarket_funder_address,
        )


@dataclass(frozen=True, slots=True)
class DerivedApiCredentials:
    api_key: str
    api_secret: str
    api_passphrase: str


class PolymarketTradingClient:
    """对官方 `py-clob-client` 的轻量封装。

    这里把 L1 创建/派生 API creds、L2 HMAC headers 和已签名订单构造集中封装，
    避免把官方 SDK 对象泄漏到 app / domain 层。
    """

    def __init__(
        self,
        *,
        host: str,
        credentials: PolymarketCredentials,
    ) -> None:
        self._host = host
        self._credentials = credentials
        self._client: Any | None = None
        self._api_creds: DerivedApiCredentials | None = None
        if credentials.has_api_credentials:
            self._api_creds = DerivedApiCredentials(
                api_key=credentials.api_key or "",
                api_secret=credentials.api_secret or "",
                api_passphrase=credentials.api_passphrase or "",
            )
        self._lock = threading.RLock()

    def get_address(self) -> str:
        client = self._ensure_client(require_l2=False)
        return str(client.get_address())

    def get_api_credentials(self) -> DerivedApiCredentials:
        with self._lock:
            self._ensure_client(require_l2=True)
            if self._api_creds is None:
                raise RuntimeError("failed to load Polymarket API credentials")
            return self._api_creds

    @property
    def signature_type(self) -> int:
        return self._credentials.signature_type

    def build_l2_headers(
        self,
        *,
        method: str,
        request_path: str,
        body: Any | None = None,
    ) -> dict[str, str]:
        exported = _require_py_clob_client()
        client = self._ensure_client(require_l2=True)
        creds = self.get_api_credentials()
        request_args = exported["request_args"](
            method=method.upper(),
            request_path=request_path,
            body=body,
            serialized_body=_json_body(body),
        )
        headers = exported["create_level_2_headers"](
            client.signer,
            exported["api_creds"](
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
            ),
            request_args,
        )
        return {str(key): str(value) for key, value in headers.items()}

    def create_signed_order(self, request: OrderExecutionRequest) -> Any:
        exported = _require_py_clob_client()
        client = self._ensure_client(require_l2=False)
        order_type_text = _order_type_text(request.order_type).upper()
        official_order_type = getattr(exported["order_type"], order_type_text)

        if request.side is not None and request.side.value == "BUY":
            if request.amount_usdc is None:
                raise ValueError("BUY order requires amount_usdc")
            if _is_market_order_type(request.order_type):
                order_args = exported["market_order_args"](
                    token_id=request.token_id,
                    amount=float(request.amount_usdc),
                    side=request.side.value,
                    price=0 if request.price is None else float(request.price),
                    order_type=official_order_type,
                )
                return client.create_market_order(order_args)
            if not _is_limit_order_type(request.order_type):
                raise ValueError(f"unsupported BUY order type: {order_type_text}")
            if request.price is None or request.price <= 0:
                raise ValueError("BUY limit order requires price")
            order_args = exported["order_args"](
                token_id=request.token_id,
                price=float(request.price),
                size=float(request.amount_usdc / request.price),
                side=request.side.value,
            )
            return client.create_order(order_args)

        if request.side is not None and request.side.value == "SELL":
            if request.price is None or request.size_shares is None:
                raise ValueError("SELL order requires price and size_shares")
            if _is_market_order_type(request.order_type):
                order_args = exported["market_order_args"](
                    token_id=request.token_id,
                    amount=float(request.size_shares),
                    side=request.side.value,
                    price=float(request.price),
                    order_type=official_order_type,
                )
                return client.create_market_order(order_args)
            if not _is_limit_order_type(request.order_type):
                raise ValueError(f"unsupported SELL order type: {order_type_text}")
            order_args = exported["order_args"](
                token_id=request.token_id,
                price=float(request.price),
                size=float(request.size_shares),
                side=request.side.value,
            )
            return client.create_order(order_args)

        raise ValueError(f"unsupported order side for signing: {request.side!r}")

    def post_signed_order(
        self,
        signed_order: Any,
        *,
        order_type: str,
        post_only: bool = False,
    ) -> Mapping[str, Any]:
        exported = _require_py_clob_client()
        client = self._ensure_client(require_l2=True)
        official_order_type = getattr(exported["order_type"], order_type.upper())
        response = client.post_order(
            signed_order,
            orderType=official_order_type,
            post_only=post_only,
        )
        return self._normalize_response(response)

    def cancel_order(self, order_id: str) -> Mapping[str, Any]:
        client = self._ensure_client(require_l2=True)
        response = client.cancel(order_id)
        normalized = dict(self._normalize_response(response))
        normalized.setdefault("order_id", order_id)
        normalized.setdefault("status", "cancelled")
        return normalized

    def _ensure_client(self, *, require_l2: bool) -> Any:
        exported = _require_py_clob_client()
        with self._lock:
            if self._client is None:
                api_creds = None
                if self._api_creds is not None:
                    api_creds = exported["api_creds"](
                        api_key=self._api_creds.api_key,
                        api_secret=self._api_creds.api_secret,
                        api_passphrase=self._api_creds.api_passphrase,
                    )
                self._client = exported["client"](
                    self._host,
                    self._credentials.chain_id,
                    self._credentials.signing_private_key,
                    api_creds,
                    self._credentials.signature_type,
                    self._credentials.funder_address,
                )
            if require_l2 and self._api_creds is None:
                derived = self._client.create_or_derive_api_creds()
                self._api_creds = DerivedApiCredentials(
                    api_key=str(derived.api_key),
                    api_secret=str(derived.api_secret),
                    api_passphrase=str(derived.api_passphrase),
                )
                self._client.set_api_creds(
                    exported["api_creds"](
                        api_key=self._api_creds.api_key,
                        api_secret=self._api_creds.api_secret,
                        api_passphrase=self._api_creds.api_passphrase,
                    )
                )
            return self._client

    def _normalize_response(self, response: Any) -> Mapping[str, Any]:
        if isinstance(response, Mapping):
            normalized = {str(key): value for key, value in response.items()}
        else:
            normalized = {"raw_response": response}
        order_id = (
            normalized.get("order_id")
            or normalized.get("orderID")
            or normalized.get("orderId")
            or normalized.get("id")
        )
        if order_id is not None:
            normalized["order_id"] = str(order_id)
        trade_id = normalized.get("trade_id") or normalized.get("tradeID") or normalized.get("tradeId")
        if trade_id is None:
            trade_ids = normalized.get("tradeIDs") or normalized.get("trade_ids")
            if isinstance(trade_ids, (list, tuple)) and trade_ids:
                trade_id = trade_ids[0]
        if trade_id is not None:
            normalized["trade_id"] = str(trade_id)
        reason = _response_reason(normalized)
        if normalized.get("success") is False or reason:
            normalized["status"] = "rejected"
            if reason:
                normalized["reason"] = reason
        elif "status" not in normalized:
            if normalized.get("canceled") is True or normalized.get("cancelled") is True:
                normalized["status"] = "cancelled"
        return normalized


def _response_reason(response: Mapping[str, Any]) -> str:
    return _text(
        response.get("reason")
        or response.get("errorMsg")
        or response.get("error_msg")
        or response.get("error")
    ) or ""


def _response_order_id(response: Mapping[str, Any]) -> str | None:
    return _text(
        response.get("order_id")
        or response.get("orderID")
        or response.get("orderId")
        or response.get("id")
    )


def _response_trade_id(response: Mapping[str, Any]) -> str | None:
    trade_id = _text(response.get("trade_id") or response.get("tradeID") or response.get("tradeId"))
    if trade_id is not None:
        return trade_id
    trade_ids = response.get("tradeIDs") or response.get("trade_ids")
    if isinstance(trade_ids, (list, tuple)) and trade_ids:
        return _text(trade_ids[0])
    return None


def _response_amounts(
    response: Mapping[str, Any],
    request: OrderExecutionRequest,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    making_amount = _fixed_6_decimal(response.get("makingAmount") or response.get("making_amount"))
    taking_amount = _fixed_6_decimal(response.get("takingAmount") or response.get("taking_amount"))
    raw_status = (_text(response.get("status")) or "").lower()
    terminal_match = raw_status == "matched"

    matched_shares: Decimal | None = None
    remaining_shares: Decimal | None = None
    spent_usdc: Decimal | None = None
    notional_usdc: Decimal | None = None

    if request.side == OrderSide.BUY:
        notional_usdc = making_amount
        if terminal_match:
            matched_shares = taking_amount
            spent_usdc = making_amount
            remaining_shares = _remaining_shares_after_match(request, matched_shares)
        elif raw_status in {"live", "delayed", "unmatched"}:
            remaining_shares = taking_amount
    elif request.side == OrderSide.SELL:
        notional_usdc = taking_amount
        if terminal_match:
            matched_shares = making_amount
            spent_usdc = taking_amount
            remaining_shares = _remaining_shares_after_match(request, matched_shares)
        elif raw_status in {"live", "delayed", "unmatched"}:
            remaining_shares = making_amount

    return matched_shares, remaining_shares, spent_usdc, notional_usdc


def _remaining_shares_after_match(
    request: OrderExecutionRequest,
    matched_shares: Decimal | None,
) -> Decimal | None:
    if matched_shares is None:
        return None
    if _is_market_order_type(request.order_type):
        return Decimal("0")
    requested_shares = _requested_shares(request)
    if requested_shares is None:
        return None
    return max(requested_shares - matched_shares, Decimal("0"))


def _requested_shares(request: OrderExecutionRequest) -> Decimal | None:
    if request.side == OrderSide.BUY:
        if request.amount_usdc is None or request.price is None or request.price <= 0:
            return None
        return request.amount_usdc / request.price
    if request.side == OrderSide.SELL:
        return request.size_shares
    return None


def _execution_status(
    response: Mapping[str, Any],
    request: OrderExecutionRequest,
    *,
    matched_shares: Decimal | None,
) -> OrderResultStatus | str | None:
    raw_status = (_text(response.get("status")) or "").lower()
    reason = _response_reason(response).lower()
    if _is_no_fill_response(reason, request):
        return OrderResultStatus.NO_FILL
    if response.get("success") is False or raw_status == "rejected" or reason:
        return OrderResultStatus.REJECTED
    if raw_status == "matched":
        return (
            OrderResultStatus.FULL_FILL
            if _is_full_fill(request, matched_shares)
            else OrderResultStatus.PARTIAL_FILL
        )
    if raw_status in {"live", "delayed", "unmatched"}:
        return OrderResultStatus.LIVE
    return _text(response.get("status"))


def _is_no_fill_response(reason: str, request: OrderExecutionRequest) -> bool:
    if not _is_market_order_type(request.order_type):
        return False
    return (
        "no orders found to match with fak order" in reason
        or "couldn't be fully filled" in reason
        or "could not be fully filled" in reason
        or "fok orders are fully filled or killed" in reason
        or "fok orders are filled or killed" in reason
    )


def _is_full_fill(request: OrderExecutionRequest, matched_shares: Decimal | None) -> bool:
    if matched_shares is None:
        return True
    requested_shares = _requested_shares(request)
    if requested_shares is None or requested_shares <= 0:
        return True
    return matched_shares >= requested_shares - Decimal("0.000001")


class PolymarketOrderExecutionClient:
    """`OrderExecutor` 的生产 Polymarket 适配器。"""

    def __init__(self, trading_client: PolymarketTradingClient) -> None:
        self._trading_client = trading_client
        self._signed_orders: dict[str, Any] = {}
        self._lock = threading.RLock()

    def sign_order(self, request: OrderExecutionRequest) -> OrderExecutionResponse:
        if request.action == "submit":
            signed_order = self._trading_client.create_signed_order(request)
            with self._lock:
                self._signed_orders[request.fingerprint()] = signed_order
            return OrderExecutionResponse(
                status="signed",
                raw_response={
                    "signed": True,
                    "action": request.action,
                    "idempotency_key": request.idempotency_key,
                },
                reason="signed",
            )

        if request.action == "replace":
            replacement_request = OrderExecutionRequest(
                action="submit",
                trace_id=request.trace_id,
                idempotency_key=request.idempotency_key,
                condition_id=request.condition_id,
                token_id=request.token_id,
                market_slug=request.market_slug,
                side=OrderSide.SELL,
                order_type=OrderType.GTC,
                price=request.new_price,
                size_shares=request.size_shares,
                post_only=request.post_only,
                reason=request.reason,
                retry_count=request.retry_count,
                timestamps=request.timestamps,
            )
            signed_order = self._trading_client.create_signed_order(replacement_request)
            with self._lock:
                self._signed_orders[request.fingerprint()] = signed_order
            return OrderExecutionResponse(
                status="signed",
                raw_response={
                    "signed": True,
                    "action": request.action,
                    "idempotency_key": request.idempotency_key,
                },
                reason="signed",
            )

        self._trading_client.get_api_credentials()
        return OrderExecutionResponse(
            status="signed",
            raw_response={"signed": True, "action": request.action},
            reason="signed",
        )

    def submit_order(self, request: OrderExecutionRequest) -> OrderExecutionResponse:
        with self._lock:
            signed_order = self._signed_orders.pop(request.fingerprint(), None)
        if signed_order is None:
            signed_order = self._trading_client.create_signed_order(request)
        response = self._trading_client.post_signed_order(
            signed_order,
            order_type=request.order_type.value if request.order_type is not None else "GTC",
            post_only=request.post_only,
        )
        matched_shares, remaining_shares, spent_usdc, notional_usdc = _response_amounts(
            response,
            request,
        )
        return OrderExecutionResponse(
            status=_execution_status(response, request, matched_shares=matched_shares),
            order_id=_response_order_id(response),
            trade_id=_response_trade_id(response),
            matched_shares=(
                _decimal(response.get("matched_shares") or response.get("filled_shares"))
                or matched_shares
            ),
            remaining_shares=_decimal(response.get("remaining_shares")) or remaining_shares,
            spent_usdc=_decimal(response.get("spent_usdc") or response.get("amount_usdc")) or spent_usdc,
            notional_usdc=_decimal(response.get("notional_usdc")) or notional_usdc,
            raw_response=response,
            reason=_response_reason(response) or "submitted",
            retryable=False,
        )

    def cancel_order(self, request: OrderExecutionRequest) -> OrderExecutionResponse:
        if not request.order_id:
            raise ValueError("cancel_order requires order_id")
        response = self._trading_client.cancel_order(request.order_id)
        return OrderExecutionResponse(
            status=_text(response.get("status")) or "cancelled",
            order_id=_text(response.get("order_id")) or request.order_id,
            raw_response=response,
            reason=_text(response.get("reason")) or "cancelled",
            retryable=False,
        )

    def replace_order(self, request: OrderExecutionRequest) -> OrderExecutionResponse:
        if not request.order_id:
            raise ValueError("replace_order requires order_id")
        cancel_response = self._trading_client.cancel_order(request.order_id)
        replacement_request = OrderExecutionRequest(
            action="submit",
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
            condition_id=request.condition_id,
            token_id=request.token_id,
            market_slug=request.market_slug,
            side=OrderSide.SELL,
            order_type=OrderType.GTC,
            price=request.new_price,
            size_shares=request.size_shares,
            post_only=request.post_only,
            reason=request.reason,
            retry_count=request.retry_count,
            timestamps=request.timestamps,
        )
        with self._lock:
            signed_order = self._signed_orders.pop(request.fingerprint(), None)
        if signed_order is None:
            signed_order = self._trading_client.create_signed_order(replacement_request)
        response = dict(
            self._trading_client.post_signed_order(
                signed_order,
                order_type=request.order_type.value if request.order_type is not None else "GTC",
                post_only=request.post_only,
            )
        )
        response["cancelled_order_id"] = request.order_id
        if "reason" not in response and "reason" in cancel_response:
            response["reason"] = cancel_response["reason"]
        return OrderExecutionResponse(
            status=_text(response.get("status")) or "live",
            order_id=_text(response.get("order_id")),
            trade_id=_text(response.get("trade_id")),
            raw_response=response,
            reason=_text(response.get("reason")) or "replaced",
            retryable=False,
        )


def build_order_execution_client(settings: Settings) -> PolymarketOrderExecutionClient | None:
    trading_client = build_trading_client(settings)
    if trading_client is None:
        return None
    return PolymarketOrderExecutionClient(trading_client)


def build_trading_client(settings: Settings) -> PolymarketTradingClient | None:
    credentials = PolymarketCredentials.from_settings(settings)
    if credentials is None:
        return None
    _require_py_clob_client()
    return PolymarketTradingClient(
        host=settings.polymarket_clob_host,
        credentials=credentials,
    )


__all__ = [
    "DerivedApiCredentials",
    "PolymarketCredentials",
    "PolymarketOrderExecutionClient",
    "PolymarketTradingClient",
    "build_trading_client",
    "build_order_execution_client",
]
