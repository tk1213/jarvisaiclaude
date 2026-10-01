"""FlowAccount products and product sets, kept in their own database file (backend/data/flowaccount/catalog.db)
so they're easy to open and edit with DB Browser for SQLite, apart from devices, chats and documents."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import CatalogBase
from app.models import utcnow


class Product(CatalogBase):
    """Copy of the FlowAccount product list (refreshed by the dashboard's "อัปเดตสินค้า" button)."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowaccount_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(256), index=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    price_includes_vat: Mapped[bool] = mapped_column(Boolean, default=False)
    type: Mapped[int] = mapped_column(Integer, default=3)  # 1 service, 3 non-inventory, 5 inventory
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProductSet(CatalogBase):
    """A named set of products a customer orders again and again ("ชุด A")."""

    __tablename__ = "product_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    customer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Goes into the document's หมายเหตุ when this set is quoted (e.g. warranty or installation terms).
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProductSetItem(CatalogBase):
    __tablename__ = "product_set_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("product_sets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # By name, so a product list refresh doesn't break the set; the price comes from the list unless fixed here.
    product: Mapped[str] = mapped_column(String(256))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
