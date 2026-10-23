"""AI Commerce Copilot: authorized order import, explainable classification and repurchase insights."""
from __future__ import annotations

import csv
import io
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'demo.db'}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("platform", "order_id", name="uq_platform_order"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    customer_id: Mapped[str] = mapped_column(String(80), index=True)
    product_name: Mapped[str] = mapped_column(String(240))
    amount: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    ordered_at: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(60), default="其他")
    category_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    category_reason: Mapped[str] = mapped_column(String(240), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


app = FastAPI(title="AI Commerce Copilot", version="1.0.0", description="授权订单数据分析演示系统")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

CATEGORY_WORDS = {
    "食品饮料": ["咖啡", "茶", "零食", "坚果", "牛奶", "麦片", "饼干", "饮料", "食品", "巧克力", "蜂蜜"],
    "美妆个护": ["面霜", "精华", "洗发", "护肤", "防晒", "洁面", "口红", "面膜", "牙膏", "洗护"],
    "家居生活": ["收纳", "床品", "水杯", "锅", "清洁", "纸巾", "家居", "香薰", "毛巾", "垃圾袋"],
    "数码配件": ["耳机", "充电", "键盘", "鼠标", "数据线", "支架", "数码", "移动电源"],
    "母婴用品": ["尿裤", "奶瓶", "婴儿", "辅食", "湿巾", "母婴", "纸尿裤"],
}

REPEAT_DAYS = {"食品饮料": 35, "美妆个护": 60, "家居生活": 90, "数码配件": 180, "母婴用品": 30, "其他": 75}


def classify(product_name: str) -> tuple[str, float, str]:
    """A deterministic, explainable baseline that can be replaced by a model adapter."""
    text = (product_name or "").lower()
    hits = [(category, [word for word in words if word in text]) for category, words in CATEGORY_WORDS.items()]
    hits = [(category, words) for category, words in hits if words]
    if not hits:
        return "其他", 0.55, "未命中品类词典，归入其他；可由运营复核"
    category, words = max(hits, key=lambda item: len(item[1]))
    confidence = min(0.98, 0.78 + 0.08 * (len(words) - 1))
    return category, confidence, f"商品名称命中关键词：{'、'.join(words)}"


def as_order(row: dict[str, Any]) -> dict[str, Any]:
    category, confidence, reason = classify(row["product_name"])
    return {
        "order_id": str(row["order_id"]).strip(), "platform": str(row.get("platform") or "演示商城").strip(),
        "customer_id": str(row["customer_id"]).strip(), "product_name": str(row["product_name"]).strip(),
        "amount": float(row["amount"]), "quantity": int(row.get("quantity") or 1),
        "ordered_at": date.fromisoformat(str(row["ordered_at"])[:10]), "category": category,
        "category_confidence": confidence, "category_reason": reason,
    }


def seed_demo() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Order)):
            return
        rng = random.Random(20261022)
        products = [
            ("食品饮料", ["云南挂耳咖啡礼盒", "每日坚果混合装", "低温纯牛奶 12 瓶", "桂花乌龙茶"], [29, 49, 59, 39]),
            ("美妆个护", ["神经酰胺保湿面霜", "氨基酸洁面乳", "轻薄防晒乳", "修护精华液"], [89, 69, 79, 129]),
            ("家居生活", ["厨房收纳盒", "纯棉毛巾套装", "香薰蜡烛", "厨房清洁湿巾"], [45, 35, 59, 25]),
            ("数码配件", ["无线蓝牙耳机", "快充数据线", "铝合金电脑支架"], [199, 29, 89]),
            ("母婴用品", ["婴儿棉柔湿巾", "成长裤纸尿裤", "婴儿辅食米粉"], [35, 99, 49]),
        ]
        now = date.today()
        customer_ids = [f"CUS-{n:03}" for n in range(1, 61)]
        rows = []
        for n in range(1, 241):
            cid = rng.choice(customer_ids)
            category, names, prices = rng.choice(products)
            idx = rng.randrange(len(names))
            days_ago = rng.randint(0, 170)
            # Repeated buyers get realistic category-specific cadence.
            if rng.random() < .55:
                days_ago = rng.choice([8, 16, 27, 38, 52, 68, 95, 125])
            quantity = rng.choice([1, 1, 1, 2, 3])
            rows.append(Order(order_id=f"DEMO-{n:05}", platform=rng.choice(["天猫授权店", "京东自营店", "抖音小店"]),
                              customer_id=cid, product_name=names[idx], amount=prices[idx] * quantity,
                              quantity=quantity, ordered_at=now - timedelta(days=days_ago),
                              category=category, category_confidence=.91, category_reason=f"演示种子数据：{category}"))
        db.add_all(rows)
        db.commit()


@app.on_event("startup")
def startup() -> None:
    seed_demo()


@app.get("/")
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "database": "mysql" if DATABASE_URL.startswith("mysql") else "sqlite"}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    with SessionLocal() as db:
        orders = list(db.scalars(select(Order)))
    today = date.today()
    last_30 = [o for o in orders if o.ordered_at >= today - timedelta(days=30)]
    cats: dict[str, int] = {}
    for o in orders:
        cats[o.category] = cats.get(o.category, 0) + 1
    return {"order_count": len(orders), "revenue": round(sum(o.amount for o in orders), 2),
            "customers": len({o.customer_id for o in orders}), "orders_30d": len(last_30),
            "revenue_30d": round(sum(o.amount for o in last_30), 2), "categories": cats,
            "platforms": sorted({o.platform for o in orders}), "refreshed_at": datetime.now().isoformat(timespec="minutes")}


@app.get("/api/orders")
def get_orders(q: str = "", category: str = "", platform: str = "", limit: int = 200) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        stmt = select(Order).order_by(Order.ordered_at.desc(), Order.id.desc()).limit(min(max(limit, 1), 500))
        if category:
            stmt = stmt.where(Order.category == category)
        if platform:
            stmt = stmt.where(Order.platform == platform)
        if q:
            stmt = stmt.where((Order.product_name.contains(q)) | (Order.customer_id.contains(q)) | (Order.order_id.contains(q)))
        rows = db.scalars(stmt).all()
        return [{"order_id": o.order_id, "platform": o.platform, "customer_id": o.customer_id,
                 "product_name": o.product_name, "amount": o.amount, "quantity": o.quantity,
                 "ordered_at": o.ordered_at.isoformat(), "category": o.category,
                 "category_confidence": o.category_confidence, "category_reason": o.category_reason} for o in rows]


@app.get("/api/recommendations")
def recommendations() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        orders = list(db.scalars(select(Order).order_by(Order.ordered_at)).all())
    groups: dict[tuple[str, str], list[Order]] = {}
    for o in orders:
        groups.setdefault((o.customer_id, o.category), []).append(o)
    today = date.today()
    results = []
    for (customer_id, category), items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda o: o.ordered_at)
        gaps = [(items[i].ordered_at - items[i-1].ordered_at).days for i in range(1, len(items))]
        avg_gap = max(7, round(sum(gaps) / len(gaps)))
        last = items[-1]
        elapsed = max(0, (today - last.ordered_at).days)
        due_ratio = elapsed / avg_gap
        if due_ratio < .65:
            continue
        likelihood = min(97, round(42 + due_ratio * 35 + min(len(items), 8) * 2))
        status = "建议触达" if due_ratio >= 1 else "即将复购"
        results.append({"customer_id": customer_id, "category": category, "last_product": last.product_name,
                        "last_order_date": last.ordered_at.isoformat(), "order_count": len(items),
                        "avg_cycle_days": avg_gap, "days_since_last": elapsed,
                        "predicted_date": (last.ordered_at + timedelta(days=avg_gap)).isoformat(),
                        "likelihood": likelihood, "status": status,
                        "reason": f"该客户购买{category}{len(items)}次，平均间隔{avg_gap}天；距上次购买{elapsed}天"})
    return sorted(results, key=lambda x: (x["likelihood"], x["days_since_last"]), reverse=True)[:60]


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(400, "请上传 CSV 文件")
    try:
        raw = (await file.read()).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        required = {"order_id", "customer_id", "product_name", "amount", "ordered_at"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise HTTPException(400, f"CSV 必须包含列：{', '.join(sorted(required))}")
        rows = [as_order(row) for row in reader]
    except (UnicodeDecodeError, ValueError, KeyError) as exc:
        raise HTTPException(400, f"CSV 内容解析失败：{exc}") from exc
    if not rows:
        raise HTTPException(400, "CSV 中没有可导入的订单")
    if len(rows) > 10000:
        raise HTTPException(413, "单次最多导入 10000 条")
    created = skipped = 0
    with SessionLocal() as db:
        for row in rows:
            exists = db.scalar(select(Order.id).where(Order.platform == row["platform"], Order.order_id == row["order_id"]))
            if exists:
                skipped += 1
                continue
            db.add(Order(**row)); created += 1
        db.commit()
    return {"imported": created, "skipped": skipped, "classified": created, "message": f"导入 {created} 条，重复跳过 {skipped} 条"}

