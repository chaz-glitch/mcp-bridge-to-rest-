"""
Distru MCP Bridge Server
=========================

WHAT THIS IS
Distru does not have its own MCP server - it has a plain REST API. Claude's
"Custom Connector" screen only speaks MCP. This file is the bridge: it exposes
a small set of MCP tools (things Claude can call), and each tool internally
makes a normal REST call to Distru's real API (base URL: https://app.distru.com,
confirmed from Distru's own docs at https://apidocs.distru.dev/).

WHAT IT COVERS (matched directly to what was asked for)
  - Orders       -> list_orders, get_order
  - Revenue      -> derived from orders/invoices/payments totals (see note below
                     on pre-built Distru reports, not yet wired in)
  - Deliveries   -> order delivery_datetime/shipping_location + list_vehicles
  - Inventory    -> list_inventory, list_batches
  - Recipe builders -> list_products (includes bill_of_materials), list_assemblies
  - Client list  -> list_companies, get_company, list_contacts

WHAT'S NOT YET WIRED IN, ON PURPOSE
  Distru's docs describe rich pre-built reports (Sales By Product, Cost of Goods
  Sold, Inventory Valuation, etc.) - their RESPONSE SHAPE is documented, but the
  exact URL path to call each one was not visible in what I could fetch. Rather
  than guess at a path and ship something that silently 404s, this file sticks
  to the endpoints Distru's docs showed a complete, working example for (the
  standard /public/v1/<resource> pattern, demonstrated live for orders). Revenue
  questions can still be answered from order/invoice totals directly - just not
  from Distru's nicer pre-aggregated report views yet. Confirm the report paths
  (ask Distru support, or check the interactive request-builder on their docs
  site) and they can be added the same way as everything below.

IMPORTANT - THIS HAS NOT BEEN RUN AGAINST THE REAL DISTRU API
I built this sandboxed, with no internet access to install the `mcp` package or
call Distru's live API to confirm behavior end to end. The endpoint paths and
request/response shapes below come directly from Distru's own published docs,
and the MCP server pattern (FastMCP, @mcp.tool decorators, streamable-http
transport) is the standard, current way to build this - but until this actually
runs somewhere with a real network connection and a real token, treat it as a
strong first draft, not a guarantee. If something errors on first deploy, send
me the exact error and we'll fix it together.

DEPLOYMENT (what happens after this file exists)
This needs to run continuously somewhere on the internet with a real HTTPS
address - it can't run inside a Claude chat, since nothing here stays running
once a conversation ends. A small always-on host (e.g. Railway, Render, Fly.io)
works well and often has a free tier sufficient for this. Once deployed, you'll
get a URL like https://your-app.up.railway.app - THAT is what goes into
Claude's Custom Connector URL field, not Distru's own URL and not your token.

SETUP
    pip install mcp requests

    Set your Distru API token as an environment variable - never hardcode it
    in this file:
        export DISTRU_API_TOKEN="your token here"

    Run locally to test:
        python distru_mcp_server.py

    The hosting platform you deploy to will set DISTRU_API_TOKEN the same way,
    usually through an "Environment Variables" section in its dashboard.
"""

import os
import sys
import requests

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as original_error:
    # The same import kept failing after a requirements.txt guess that didn't
    # pan out. Rather than guess a third time, report exactly what IS
    # actually installed - the real fix is whatever this prints, not another
    # guess at what it might be.
    print("=" * 70, file=sys.stderr)
    print("DIAGNOSTIC: 'from mcp.server.fastmcp import FastMCP' failed.", file=sys.stderr)
    print(f"Original error: {original_error}", file=sys.stderr)
    try:
        import mcp
        print(f"mcp package IS installed, version: {getattr(mcp, '__version__', 'unknown')}", file=sys.stderr)
        print(f"mcp package location on disk: {mcp.__file__}", file=sys.stderr)
        print(f"Top-level names inside mcp: {sorted(dir(mcp))}", file=sys.stderr)
        try:
            import mcp.server as mcp_server
            print(f"mcp.server IS importable. Names inside it: {sorted(dir(mcp_server))}", file=sys.stderr)
        except Exception as inner_e:
            print(f"mcp.server itself failed to import: {inner_e}", file=sys.stderr)
    except ModuleNotFoundError:
        print("mcp package is NOT installed at all - pip install did not bring it in.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    raise

# Starlette ships as a dependency of mcp[cli] (confirmed via a real deploy log - starlette
# appeared in the installed-packages list), so this import should be reliable without
# adding a new line to requirements.txt.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import uvicorn

DISTRU_BASE_URL = "https://app.distru.com"
DISTRU_API_TOKEN = os.environ.get("DISTRU_API_TOKEN")

if not DISTRU_API_TOKEN:
    raise RuntimeError(
        "DISTRU_API_TOKEN environment variable is not set. "
        "Set it before starting this server - see the SETUP note at the top of this file."
    )

# Bridge-level authentication (added 2026-08-07). Everything above protects the Distru
# token; this protects the bridge itself. Before this, ANYONE who found this server's
# public URL could call it and pull real Distru data through it, without ever needing the
# Distru token themselves - the server trusted every request unconditionally. This checks
# every incoming request for a shared secret (via the X-Bridge-Secret header, or a ?key=
# query parameter on the URL for cases where sending a custom header isn't practical) before
# letting it anywhere near Distru. This secret is intentionally separate from
# DISTRU_API_TOKEN - rotating one never requires touching the other.
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET")
if not BRIDGE_SECRET:
    raise RuntimeError(
        "BRIDGE_SECRET environment variable is not set. This server refuses to start "
        "without it - running an unauthenticated bridge to real business data is exactly "
        "the gap this update exists to close. Set a strong random value for it (the same "
        "way DISTRU_API_TOKEN is set) before starting this server."
    )

class BridgeAuthMiddleware(BaseHTTPMiddleware):
    """Rejects any request that doesn't carry the correct shared secret, before it gets
    anywhere near Distru. Checked in two places for practicality: the X-Bridge-Secret
    header (the more standard way to send a credential), or a ?key= query parameter on the
    URL itself (for any situation where sending a custom header isn't straightforward - a
    query-string secret is a well-established, if slightly weaker, fallback for exactly
    this kind of lightweight service). Either one matching is sufficient.
    Returns a plain 404, not 401 - this was originally 401, and that specifically appears
    to make OAuth-aware MCP clients (Claude's connector included) assume the endpoint wants
    an OAuth handshake and try to negotiate one, producing a confusing "couldn't register
    with sign-in service" error that has nothing to do with the actual secret check. A 404
    carries no such connotation - it just looks like nothing is there, which is also,
    incidentally, a strictly better security posture (doesn't even confirm an authenticated
    endpoint exists at that URL) than a 401/403 would."""
    async def dispatch(self, request, call_next):
        provided = request.headers.get("x-bridge-secret") or request.query_params.get("key")
        if provided != BRIDGE_SECRET:
            return JSONResponse({"error": "not found"}, status_code=404)
        return await call_next(request)


_resolved_port = int(os.environ.get("PORT", 8000))
print(f"DIAGNOSTIC: os.environ PORT = {os.environ.get('PORT')!r}", flush=True)
print(f"DIAGNOSTIC: resolved port that FastMCP will use = {_resolved_port}", flush=True)
print(f"DIAGNOSTIC: FastMCP version = {getattr(__import__('mcp'), '__version__', 'unknown')}", flush=True)

mcp = FastMCP(
    "distru",
    # 0.0.0.0 means "accept connections from anywhere," not just from inside
    # this same container - without this, Railway's public domain would have
    # nothing to actually reach, regardless of which port is right.
    host="0.0.0.0",
    # Respect whatever port Railway (or any host) assigns via PORT; fall back
    # to 8000 only for running this locally on your own machine.
    port=_resolved_port,
)


def _distru_get(path: str, params: dict | None = None) -> dict:
    """Shared helper: makes an authenticated GET request to Distru's REST API
    and returns the parsed JSON body. Every tool below uses this, so auth and
    error handling only need to live in one place."""
    url = f"{DISTRU_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {DISTRU_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _paginate_all(path: str, params: dict | None = None, max_pages: int = 20) -> list:
    """Follows Distru's next_page links automatically, up to max_pages, and
    returns the combined list of records. Distru's own pagination pattern
    (documented in their API docs) is a page[number] query param with a
    next_page URL in the response when more data is available."""
    params = dict(params or {})
    params.setdefault("page[number]", 1)
    all_records = []
    page = 1
    while page <= max_pages:
        params["page[number]"] = page
        body = _distru_get(path, params)
        records = body.get("data", [])
        all_records.extend(records)
        if not body.get("next_page"):
            break
        page += 1
    return all_records


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@mcp.tool()
def list_orders(updated_after: str | None = None, updated_before: str | None = None,
                 max_pages: int = 5) -> list:
    """List sales orders from Distru, with their status, totals, delivery date,
    and shipping location. Optionally filter by when the order was last updated
    (ISO 8601 datetime strings, e.g. "2026-07-01T00:00:00Z"). Use this for
    questions about order volume, order status, or what's scheduled for
    delivery. max_pages caps how many pages of ~results are pulled (each page
    is one API call) - raise it for a full historical pull, keep it low for a
    quick recent-activity check."""
    params = {}
    if updated_after or updated_before:
        params["updated_datetime"] = f"{updated_after or ''},{updated_before or ''}"
    return _paginate_all("/public/v1/orders", params, max_pages=max_pages)


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Get full details for one specific sales order by its Distru ID,
    including every line item, charges, taxes, and shipping/billing
    locations."""
    return _distru_get(f"/public/v1/orders/{order_id}")


# ---------------------------------------------------------------------------
# Revenue (orders + invoices + payments, until Distru's report endpoints are
# confirmed - see the module docstring)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_invoices(updated_after: str | None = None, updated_before: str | None = None,
                   max_pages: int = 5) -> list:
    """List invoices from Distru, including total, paid amount, remaining
    (outstanding) amount, and status. Use this for revenue and
    accounts-receivable questions - "what's outstanding", "what came in this
    month", etc."""
    params = {}
    if updated_after or updated_before:
        params["updated_datetime"] = f"{updated_after or ''},{updated_before or ''}"
    return _paginate_all("/public/v1/invoices", params, max_pages=max_pages)


@mcp.tool()
def list_payments(updated_after: str | None = None, updated_before: str | None = None,
                   max_pages: int = 5) -> list:
    """List payments recorded in Distru, each tied to either an invoice or a
    purchase. Use this alongside list_invoices for a fuller revenue picture -
    an invoice's remaining_amount only tells you what's left, this tells you
    what actually came in and when."""
    params = {}
    if updated_after or updated_before:
        params["updated_datetime"] = f"{updated_after or ''},{updated_before or ''}"
    return _paginate_all("/public/v1/payments", params, max_pages=max_pages)


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------

@mcp.tool()
def list_vehicles() -> list:
    """List delivery vehicles configured in Distru (make, model, license
    plate). Cross-reference with orders' delivery_datetime and
    shipping_location for a fuller delivery picture - Distru ties vehicles to
    deliveries at the transfer/manifest level, not directly on each order
    record."""
    return _paginate_all("/public/v1/vehicles")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@mcp.tool()
def list_inventory(max_pages: int = 10) -> list:
    """List current inventory levels across all products: active, available
    (active minus reserved), and reserved quantities, plus cost per unit. This
    is the live on-hand picture, not a historical report."""
    return _paginate_all("/public/v1/inventories", max_pages=max_pages)


@mcp.tool()
def list_batches(max_pages: int = 10) -> list:
    """List product batches, including batch number, cost per unit, and
    manufactured date. Useful for tracing a specific production run or
    checking batch-level costing rather than aggregate inventory."""
    return _paginate_all("/public/v1/batches", max_pages=max_pages)


# ---------------------------------------------------------------------------
# Recipe builders (Bill of Materials + Assemblies)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_products(max_pages: int = 10) -> list:
    """List products, including each product's bill_of_materials when it has
    one - Distru's term for a recipe: the specific inputs (other products, by
    quantity) and additional costs that make up a manufactured product. This
    is the right tool for "what goes into X" questions."""
    return _paginate_all("/public/v1/products", max_pages=max_pages)


@mcp.tool()
def list_assemblies(max_pages: int = 5) -> list:
    """List assemblies - actual production runs in Distru that consume
    bill-of-materials inputs and produce outputs. Use this for "what did we
    actually produce" questions, as opposed to list_products' bill_of_materials
    which describes the recipe in the abstract, not a specific production
    event."""
    return _paginate_all("/public/v1/assemblies", max_pages=max_pages)


# ---------------------------------------------------------------------------
# Client list
# ---------------------------------------------------------------------------

@mcp.tool()
def list_companies(max_pages: int = 10) -> list:
    """List companies in Distru's CRM - both customers and vendors/suppliers,
    distinguished by their relationship_type field. This is the client list."""
    return _paginate_all("/public/v1/companies", max_pages=max_pages)


@mcp.tool()
def get_company(company_id: str) -> dict:
    """Get full details for one specific company by its Distru ID, including
    its locations and licenses."""
    return _distru_get(f"/public/v1/companies/{company_id}")


@mcp.tool()
def list_contacts(max_pages: int = 10) -> list:
    """List individual contacts (people) in Distru's CRM, each linked to a
    company. Use this when the question is about a specific person rather
    than the business they work for."""
    return _paginate_all("/public/v1/contacts", max_pages=max_pages)


if __name__ == "__main__":
    # DIAGNOSTIC ROLLBACK (2026-08-07): temporarily reverted to calling mcp.run() directly,
    # bypassing BridgeAuthMiddleware entirely, to isolate whether the middleware itself is
    # what's breaking the "add connector" flow - this exact server, same URL, worked
    # correctly for hours before the middleware was added, which is the strongest evidence
    # available right now. The middleware code above is untouched and ready to re-enable
    # once this is confirmed one way or the other - this is a controlled test, not
    # abandoning the security fix.
    print(f"DIAGNOSTIC: [rollback mode] calling mcp.run() directly, middleware bypassed, "
          f"host 0.0.0.0 port {_resolved_port}", flush=True)
    try:
        mcp.run(transport="streamable-http")
    except Exception as startup_error:
        print(f"DIAGNOSTIC: mcp.run() raised an exception: {startup_error!r}", flush=True)
        raise
