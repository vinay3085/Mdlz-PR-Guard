from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Installation(Base):
    __tablename__ = "installations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(Integer, unique=True, nullable=False, index=True)
    org = Column(String(255), nullable=False)
    account_login = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    installed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PRReview(Base):
    __tablename__ = "pr_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(Integer, nullable=False, index=True)
    repo_full_name = Column(String(500), nullable=False)
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String(40), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    total_findings = Column(Integer, nullable=False, default=0)
    critical_count = Column(Integer, nullable=False, default=0)
    high_count = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer)
    error_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)

    findings = relationship("Finding", back_populates="pr_review", cascade="all, delete-orphan")
    usage_entries = relationship("UsageLedger", back_populates="pr_review", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_review_id = Column(Integer, ForeignKey("pr_reviews.id"), nullable=False, index=True)
    source = Column(String(20), nullable=False)
    severity = Column(String(20), nullable=False)
    rule_id = Column(String(255))
    file_path = Column(String(1000))
    line_number = Column(Integer)
    message = Column(Text, nullable=False)
    code_snippet = Column(Text)
    dedupe_hash = Column(String(64), index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    pr_review = relationship("PRReview", back_populates="findings")


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    severity = Column(String(20), nullable=False, default="medium")
    enabled = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UsageLedger(Base):
    __tablename__ = "usage_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_review_id = Column(Integer, ForeignKey("pr_reviews.id"), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    pr_review = relationship("PRReview", back_populates="usage_entries")
