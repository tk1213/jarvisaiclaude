from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog_models import Product, ProductSet
from app.db import get_catalog_db
from app.deps import get_current_user
from app.integrations.flowaccount import FlowAccountError
from app.models import User
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
    unit_price: float | None  # the set's special price; None = the FlowAccount price
    list_price: float | None = None


class ProductSetOut(BaseModel):
    id: int
    name: str
    customer: str | None
    description: str | None = None
    remarks: str | None
    items: list[SetItemOut]


class SetItemIn(BaseModel):
    product: str = Field(min_length=1, max_length=256)
    quantity: float = Field(gt=0)
    unit: str | None = Field(default=None, max_length=32)
    unit_price: float | None = Field(default=None, ge=0)


class ProductSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=200)
    remarks: str | None = Field(default=None, max_length=2000)
    items: list[SetItemIn] = Field(min_length=1, max_length=100)


def _products(db: Session) -> list[ProductOut]:
    return [ProductOut(**catalog.product_summary(p)) for p in db.scalars(select(Product).order_by(Product.name))]


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_catalog_db), _: User = Depends(get_current_user)):
    return _products(db)


@router.post("/products/sync", response_model=list[ProductOut])
def sync_products(db: Session = Depends(get_catalog_db), _: User = Depends(get_current_user)):
    """Copy the product list from FlowAccount (the "อัปเดตสินค้า" button)."""
    try:
        catalog.sync_products(db)
    except FlowAccountError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from None
    return _products(db)


@router.get("/product-sets", response_model=list[ProductSetOut])
def list_sets(db: Session = Depends(get_catalog_db), _: User = Depends(get_current_user)):
    return catalog.list_sets(db)


@router.put("/product-sets/{set_id}", response_model=ProductSetOut)
def update_set(set_id: int, body: ProductSetIn, db: Session = Depends(get_catalog_db), _: User = Depends(get_current_user)):
    """Edit a set from the dashboard: name, description, remarks, items, quantities and special prices."""
    product_set = db.get(ProductSet, set_id)
    if product_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found")
    try:
        catalog.update_set(db, product_set, body.name, body.description, body.remarks, [i.model_dump() for i in body.items])
    except catalog.CatalogError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return next(s for s in catalog.list_sets(db) if s["id"] == set_id)


@router.delete("/product-sets/{set_id}", status_code=204)
def delete_set(set_id: int, db: Session = Depends(get_catalog_db), _: User = Depends(get_current_user)):
    product_set = db.get(ProductSet, set_id)
    if product_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found")
    catalog.delete_set(db, product_set.name)
