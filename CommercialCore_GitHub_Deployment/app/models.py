from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Date, DateTime, ForeignKey, Numeric, Text, Boolean,
    UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now():
    return datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="data_support")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200), index=True)
    dba_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Chicago")
    renewal_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    producer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    producer = relationship("User")
    contacts = relationship("Contact", cascade="all, delete-orphan", back_populates="business")
    locations = relationship("Location", cascade="all, delete-orphan", back_populates="business")
    policies = relationship("Policy", cascade="all, delete-orphan", back_populates="business")
    reviews = relationship("ReviewItem", cascade="all, delete-orphan", back_populates="business")
    account_notes = relationship("AccountNote", cascade="all, delete-orphan", back_populates="business")
    review_packets = relationship("ReviewPacket", cascade="all, delete-orphan", back_populates="business")
    tasks = relationship("Task", cascade="all, delete-orphan", back_populates="business")
    activities = relationship("Activity", cascade="all, delete-orphan", back_populates="business")
    documents = relationship("Document", cascade="all, delete-orphan", back_populates="business")
    recommendations = relationship("Recommendation", cascade="all, delete-orphan", back_populates="business")

class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    business = relationship("Business", back_populates="contacts")

class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="Primary")
    address1: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(2))
    postal_code: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    business = relationship("Business", back_populates="locations")

class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    line: Mapped[str] = mapped_column(String(100))
    policy_number_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date)
    expiration_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    annual_premium: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    business = relationship("Business", back_populates="policies")
    exposures = relationship("Exposure", cascade="all, delete-orphan", back_populates="policy")
    carrier_reference = relationship("PolicyCarrier", uselist=False, cascade="all, delete-orphan", back_populates="policy")


class PolicyCarrier(Base):
    __tablename__ = "policy_carriers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), unique=True, index=True)
    carrier_name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    policy = relationship("Policy", back_populates="carrier_reference")

class AccountNote(Base):
    __tablename__ = "account_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    business = relationship("Business", back_populates="account_notes")
    author = relationship("User")

class Exposure(Base):
    __tablename__ = "exposures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), index=True)
    exposure_type: Mapped[str] = mapped_column(String(40))
    recorded_estimate: Mapped[float] = mapped_column(Numeric(14, 2))
    cadence: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(40), default="dollars")
    reporting_due_days: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    policy = relationship("Policy", back_populates="exposures")
    entries = relationship("ReportingEntry", cascade="all, delete-orphan", back_populates="exposure")
    projections = relationship("Projection", cascade="all, delete-orphan", back_populates="exposure")
    reviews = relationship("ReviewItem", back_populates="exposure")

class ReportingEntry(Base):
    __tablename__ = "reporting_entries"
    __table_args__ = (
        UniqueConstraint("exposure_id", "period_start", "period_end", name="uq_exposure_period"),
        Index("ix_reporting_exposure_dates", "exposure_id", "period_start", "period_end"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exposure_id: Mapped[int] = mapped_column(ForeignKey("exposures.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    actual_value: Mapped[float] = mapped_column(Numeric(14, 2))
    source: Mapped[str] = mapped_column(String(40), default="manual")
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    exposure = relationship("Exposure", back_populates="entries")
    creator = relationship("User")

class ImportFile(Base):
    __tablename__ = "import_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exposure_id: Mapped[int] = mapped_column(ForeignKey("exposures.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(40))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Projection(Base):
    __tablename__ = "projections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exposure_id: Mapped[int] = mapped_column(ForeignKey("exposures.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(40))
    projected_total: Mapped[float] = mapped_column(Numeric(14, 2))
    variance_percent: Mapped[float] = mapped_column(Numeric(8, 3))
    accuracy_score: Mapped[int] = mapped_column(Integer)
    confidence_score: Mapped[int] = mapped_column(Integer)
    core_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)
    scoring_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    score_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    exposure = relationship("Exposure", back_populates="projections")

class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    exposure_id: Mapped[int | None] = mapped_column(ForeignKey("exposures.id"), nullable=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(240))
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    business = relationship("Business", back_populates="reviews")
    exposure = relationship("Exposure", back_populates="reviews")
    assignee = relationship("User")
    notes = relationship("AgencyNote", cascade="all, delete-orphan", back_populates="review")

class AgencyNote(Base):
    __tablename__ = "agency_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_items.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    review = relationship("ReviewItem", back_populates="notes")
    author = relationship("User")

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    file_name: Mapped[str] = mapped_column(String(255))
    generated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    business = relationship("Business")


class ReviewPacket(Base):
    __tablename__ = "review_packets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), default="Annual Commercial Insurance Review")
    meeting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prepared_for: Mapped[str | None] = mapped_column(String(200), nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    discussion_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    sections_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    business = relationship("Business", back_populates="review_packets")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(40), default="follow_up")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="open")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    assigned_to: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    business = relationship("Business", back_populates="tasks")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])

class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    activity_type: Mapped[str] = mapped_column(String(40), default="note")
    subject: Mapped[str] = mapped_column(String(240))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    business = relationship("Business", back_populates="activities")
    owner = relationship("User", foreign_keys=[owner_id])
    creator = relationship("User", foreign_keys=[created_by])

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(60), default="other")
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    business = relationship("Business", back_populates="documents")
    uploader = relationship("User")


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("business_id", "code", name="uq_business_recommendation_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    code: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    suggested_actions_json: Mapped[str] = mapped_column(Text, default="[]")
    source_type: Mapped[str] = mapped_column(String(40), default="business")
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    linked_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    linked_packet_id: Mapped[int | None] = mapped_column(ForeignKey("review_packets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    business = relationship("Business", back_populates="recommendations")
    linked_task = relationship("Task", foreign_keys=[linked_task_id])
    linked_packet = relationship("ReviewPacket", foreign_keys=[linked_packet_id])
    resolver = relationship("User", foreign_keys=[resolved_by])

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    actor = relationship("User")
