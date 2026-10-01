from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.integrations.flowaccount import FlowAccountError
from app.models import Product, ProductSet, User
from app.services import catalog

router = APIRouter(tags=["catalog"])


class ProductOut(BaseModel):
    name: str
    code: str
    unit: str
    price: float
    price_includes_vat: bool


class SetItemOut(BaseModel):
    product: str
    quantity: float
    unit: str | None
    unit_price: float | None


class ProductSetOut(BaseModel):
    id: int
    name: str
    customer: str | None
    remarks: str | None
    items: list[SetItemOut]


def _products(db: Session) -> list[ProductOut]:
    return [ProductOut(**catalog.product_summary(p)) for p in db.scalars(select(Product).order_by(Product.name))]


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _products(db)


@router.post("/products/sync", response_model=list[ProductOut])
def sync_products(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Copy the product list from FlowAccount (the "อัปเดตสินค้า" button)."""
    try:
        catalog.sync_products(db)
    except FlowAccountError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from None
    return _products(db)


@router.get("/product-sets", response_model=list[ProductSetOut])
def list_sets(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return catalog.list_sets(db)


@router.delete("/product-sets/{set_id}", status_code=204)
def delete_set(set_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    product_set = db.get(ProductSet, set_id)
    if product_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found")
    catalog.delete_set(db, product_set.name)
