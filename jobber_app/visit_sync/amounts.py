"""Build one Hub visits row from a Jobber visit and its invoice (amounts for contractor pay)."""

from decimal import ROUND_HALF_UP, Decimal

from jobber_app.lock_in.matching import is_internal_client
from jobber_app.work_hours.aggregate import parse_iso

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
# Per-visit-billed invoice subtotal vs its visits' line prices: outside this range needs review.
# Wide on purpose: price changes, invoice edits (229 → 129) and extra invoice items are normal.
SHARE_RATIO_MIN = Decimal("0.5")
SHARE_RATIO_MAX = Decimal("2")
MONEY_FIELDS = (
    "visit_amount",
    "discount_share",
    "tip_share",
    "line_items_total",
    "invoice_subtotal",
    "invoice_discount",
    "invoice_tips",
)


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def line_items_total(visit):
    nodes = (visit.get("lineItems") or {}).get("nodes") or []
    return money(sum(Decimal(str(n.get("totalPrice") or 0)) for n in nodes))


def allocate(total, weights):
    """
    Split ``total`` across ``weights`` keys in proportion to the weights, in whole cents that
    sum exactly to the total (largest remainder). Equal split when every weight is missing or 0.
    """
    keys = sorted(weights)
    if not keys:
        return {}
    w = {k: max(Decimal(str(weights[k] or 0)), Decimal(0)) for k in keys}
    if sum(w.values()) <= 0:
        w = {k: Decimal(1) for k in keys}
    cents = int(money(total) * 100)
    sign, cents = (-1 if cents < 0 else 1), abs(cents)
    wsum = sum(w.values())
    raw = {k: Decimal(cents) * w[k] / wsum for k in keys}
    out = {k: int(raw[k]) for k in keys}
    for k in sorted(keys, key=lambda k: (-(raw[k] - out[k]), k))[: cents - sum(out.values())]:
        out[k] += 1
    return {k: (Decimal(sign * out[k]) / 100).quantize(CENT) for k in keys}


def _share_looks_wrong(visit_id, subtotal, weights, fixed_price):
    """
    Flag a split for review when it can't be right: this visit has no price while others do, or
    (per-visit billing only) the invoice is far from the sum of its visits' prices — e.g. one
    215.00 invoice linked to 43 visits. Fixed-price line items are a period price, so their sum
    across visits is expected to exceed the invoice.
    """
    values = {k: Decimal(str(v or 0)) for k, v in weights.items()}
    total = sum(values.values())
    if total > 0 and values[visit_id] <= 0:
        return True
    if not fixed_price and total > 0:
        ratio = subtotal / total
        return ratio < SHARE_RATIO_MIN or ratio > SHARE_RATIO_MAX
    return False


def _amounts(visit, lines, invoice_weights):
    job = visit.get("job") or {}
    never_invoiced = ((job.get("invoiceSchedule") or {}).get("billingFrequency")) == "NEVER"
    fixed_price = job.get("billingType") == "FIXED_PRICE"
    invoice = visit.get("invoice")
    estimate = {
        "visit_amount": lines,
        "discount_share": ZERO,
        "tip_share": ZERO,
        "amount_rule": "estimate",
        "amount_is_estimate": True,
        "invoice_id": None,
        "invoice_subtotal": ZERO,
        "invoice_discount": ZERO,
        "invoice_tips": ZERO,
        # Fixed-price line items are a period price, not a per-visit price, so an
        # un-invoiced fixed-price visit needs a human check.
        "amount_needs_review": fixed_price,
    }
    if not invoice:
        if never_invoiced:
            # "Never invoice" clients pay the agreed job price (pre-tax). A 0.00 price or a
            # fixed-price job can't be a real per-visit price, so those still need review.
            return {
                **estimate,
                "amount_rule": "job_price",
                "amount_is_estimate": False,
                "amount_needs_review": fixed_price or lines <= 0,
            }
        return estimate

    amounts = invoice.get("amounts") or {}
    subtotal = money(amounts.get("subtotal"))
    discount = money(amounts.get("discountAmount"))
    tips = money(amounts.get("tipsTotal"))
    invoice_fields = {
        "invoice_id": invoice.get("id"),
        "invoice_subtotal": subtotal,
        "invoice_discount": discount,
        "invoice_tips": tips,
    }
    count = (invoice.get("visits") or {}).get("totalCount")
    if count == 1:
        return {
            **invoice_fields,
            "visit_amount": subtotal,
            "discount_share": discount,
            "tip_share": tips,
            "amount_rule": "invoice",
            "amount_is_estimate": False,
            "amount_needs_review": False,
        }
    if count and count > 1 and invoice_weights and visit["id"] in invoice_weights:
        return {
            **invoice_fields,
            "visit_amount": allocate(subtotal, invoice_weights)[visit["id"]],
            "discount_share": allocate(discount, invoice_weights)[visit["id"]],
            "tip_share": allocate(tips, invoice_weights)[visit["id"]],
            "amount_rule": "invoice_share",
            "amount_is_estimate": False,
            "amount_needs_review": _share_looks_wrong(visit["id"], subtotal, invoice_weights, fixed_price),
        }
    # Invoiced, but its visits couldn't be matched cleanly: keep the invoice for reference.
    return {**estimate, **invoice_fields, "amount_needs_review": True}


def build_entry(visit, tz, invoice_weights=None):
    """Hub visits row (JSON-ready: money as 2-decimal strings)."""
    job = visit.get("job") or {}
    client = visit.get("client") or {}
    lines = line_items_total(visit)
    start = visit.get("startAt")
    internal = is_internal_client(client.get("name") or "")
    entry = {
        "jobber_visit_id": visit["id"],
        "jobber_job_id": job.get("id"),
        "job_number": job.get("jobNumber"),
        "job_title": job.get("title") or "",
        "client_jobber_id": client.get("id"),
        "client_name": client.get("name") or "",
        "date": parse_iso(start).astimezone(tz).date().isoformat() if start else None,
        "status": visit.get("visitStatus") or "",
        "completed_at": visit.get("completedAt"),
        "assigned_user_ids": sorted(
            n["id"] for n in (visit.get("assignedUsers") or {}).get("nodes") or [] if n.get("id")
        ),
        "line_items_total": lines,
        "internal": internal,
        **_amounts(visit, lines, invoice_weights),
    }
    if internal:
        # Internal (CLEAN ON THE GO INC.) visits are sent as 0.00 so they never count toward pay.
        entry.update({f: ZERO for f in ("visit_amount", "discount_share", "tip_share")})
        entry["amount_needs_review"] = False
    return {k: (str(v) if k in MONEY_FIELDS else v) for k, v in entry.items()}


def deleted_entry(visit_id, last_payload):
    """Re-send a previously sent visit that no longer exists in Jobber: status deleted, 0.00 amounts."""
    entry = {**(last_payload or {}), "jobber_visit_id": visit_id}
    entry.update({f: str(ZERO) for f in MONEY_FIELDS})
    entry.update(
        status="deleted",
        invoice_id=None,
        amount_is_estimate=False,
        amount_needs_review=False,
    )
    return entry
