"""Products from FlowAccount, named product sets ("ชุด A") and repeat orders, for quick quotations."""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.integrations.flowaccount import get_flowaccount_client
from app.models import DocumentLog, Product, ProductSet, ProductSetItem


class CatalogError(ValueError):
    """Something JARVIS should tell the user (unknown set, empty set, ...)."""


# Thai tone marks and the short-vowel sign: "โช็ค", "โช๊ค" and "โชค" are the same word to a customer.
_MARKS = re.compile(r"[็-์\s]")


def _norm(text: str) -> str:
    return _MARKS.sub("", (text or "").lower())


def _tokens(text: str) -> list[str]:
    return [t for t in (_norm(w) for w in re.split(r"[\s,]+", text or "")) if t]


def sync_products(db: Session) -> list[Product]:
    """Replace the local copy with FlowAccount's product list."""
    rows = get_flowaccount_client().list_products()
    seen = set()
    for p in rows:
        fid = str(p.get("id") or p.get("code") or p.get("name"))
        seen.add(fid)
        product = db.scalar(select(Product).where(Product.flowaccount_id == fid)) or Product(flowaccount_id=fid)
        product.code = str(p.get("code") or "")
        product.name = str(p.get("name") or "").strip()
        product.unit = str(p.get("unitName") or "")
        product.price = float(p.get("sellPrice") or 0)
        product.price_includes_vat = int(p.get("sellVatType") or 3) == 1
        product.type = int(p.get("type") or 3)
        db.add(product)
    if seen:
        db.execute(delete(Product).where(Product.flowaccount_id.not_in(seen)))
    db.commit()
    return list(db.scalars(select(Product).order_by(Product.name)))


def find_products(db: Session, query: str, limit: int = 8) -> list[Product]:
    """Products whose name or code contains the most words of the query (tone marks and spaces ignored)."""
    words = _tokens(query)
    if not words:
        return []
    scored = []
    for p in db.scalars(select(Product)):
        haystack = _norm(p.name) + " " + _norm(p.code)
        hits = sum(1 for w in words if w in haystack)
        if hits:
            scored.append((hits, p))
    scored.sort(key=lambda s: (-s[0], len(s[1].name), s[1].name))
    complete = [p for hits, p in scored if hits == len(words)]
    # Every word matched: only those. Otherwise the closest few, for JARVIS to ask which one was meant.
    return (complete or [p for _, p in scored])[:limit]


def product_summary(p: Product) -> dict:
    return {"name": p.name, "code": p.code, "unit": p.unit, "price": p.price, "price_includes_vat": p.price_includes_vat}


def _exact(db: Session, name: str) -> Product | None:
    target = _norm(name)
    for p in db.scalars(select(Product)):
        if _norm(p.name) == target or (p.code and _norm(p.code) == target):
            return p
    return None


def save_set(db: Session, name: str, items: list[dict], customer: str | None = None) -> ProductSet:
    name = name.strip()
    if not name:
        raise CatalogError("ต้องตั้งชื่อชุด")
    if not items:
        raise CatalogError("ชุดต้องมีสินค้าอย่างน้อย 1 รายการ")
    clean = []
    for i in items:
        product = (i.get("product") or "").strip()
        quantity = float(i.get("quantity") or 0)
        if not product or quantity <= 0:
            raise CatalogError("ทุกรายการในชุดต้องมีชื่อสินค้าและจำนวนมากกว่า 0")
        match = _exact(db, product)
        price = i.get("unit_price")
        clean.append((match.name if match else product, quantity, float(price) if price is not None else None, i.get("unit") or (match.unit if match else None)))
    product_set = db.scalar(select(ProductSet).where(func.lower(ProductSet.name) == name.lower())) or ProductSet(name=name)
    product_set.customer = (customer or "").strip() or None
    db.add(product_set)
    db.flush()
    db.execute(delete(ProductSetItem).where(ProductSetItem.set_id == product_set.id))
    for pos, (product, quantity, price, unit) in enumerate(clean):
        db.add(ProductSetItem(set_id=product_set.id, position=pos, product=product, quantity=quantity, unit_price=price, unit=unit))
    db.commit()
    return product_set


def _get_set(db: Session, name: str) -> ProductSet:
    target = _norm(name)
    for s in db.scalars(select(ProductSet)):
        if _norm(s.name) == target:
            return s
    raise CatalogError(f"ไม่พบชุด '{name}' ชุดที่มี: {', '.join(s.name for s in db.scalars(select(ProductSet))) or '-'}")


def set_items(db: Session, product_set: ProductSet) -> list[ProductSetItem]:
    return list(db.scalars(select(ProductSetItem).where(ProductSetItem.set_id == product_set.id).order_by(ProductSetItem.position)))


def expand_set(db: Session, name: str, times: float = 1) -> dict:
    """A set's items ready for prepare_document: price fixed in the set, else the current list price."""
    product_set = _get_set(db, name)
    items = []
    for it in set_items(db, product_set):
        product = _exact(db, it.product)
        price = it.unit_price if it.unit_price is not None else (product.price if product else None)
        items.append(
            {
                "name": product.name if product else it.product,
                "quantity": it.quantity * times,
                "unit": it.unit or (product.unit if product else ""),
                "unit_price": price,
                "price_source": "ราคาพิเศษของชุด" if it.unit_price is not None else ("ราคาใน FlowAccount" if product else "ไม่มีราคา ต้องถามผู้ใช้"),
                "price_includes_vat": bool(product and product.price_includes_vat),
            }
        )
    return {"set": product_set.name, "customer": product_set.customer, "times": times, "items": items}


def list_sets(db: Session) -> list[dict]:
    return [
        {"id": s.id, "name": s.name, "customer": s.customer, "items": [{"product": i.product, "quantity": i.quantity, "unit": i.unit, "unit_price": i.unit_price} for i in set_items(db, s)]}
        for s in db.scalars(select(ProductSet).order_by(ProductSet.name))
    ]


def delete_set(db: Session, name: str) -> None:
    product_set = _get_set(db, name)
    db.execute(delete(ProductSetItem).where(ProductSetItem.set_id == product_set.id))
    db.delete(product_set)
    db.commit()


def last_order(db: Session, customer: str) -> dict:
    """The items of the newest document for a customer (name matched loosely), for "เหมือนครั้งก่อน"."""
    target = _norm(customer)
    for doc in db.scalars(select(DocumentLog).order_by(DocumentLog.id.desc()).limit(500)):
        name = (doc.payload.get("customer") or {}).get("name") or ""
        if target and (target in _norm(name) or _norm(name) in target):
            p = doc.payload["flowaccount"]
            return {
                "customer": doc.payload["customer"],
                "from_document": doc.document_serial or f"ร่าง #{doc.id}",
                "date": p["publishedOn"],
                "vat": p["isVat"],
                "vat_inclusive": p["isVatInclusive"],
                "credit_days": p["creditDays"],
                "items": [{"name": i["name"], "quantity": i["quantity"], "unit": i["unitName"], "unit_price": i["pricePerUnit"]} for i in p["items"]],
            }
    raise CatalogError(f"ยังไม่เคยมีเอกสารของลูกค้า '{customer}'")
