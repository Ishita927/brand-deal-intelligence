from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    deal_offer = "deal_offer"
    needs_more_info = "needs_more_info"
    not_a_fit = "not_a_fit"
    scam_or_phishing = "scam_or_phishing"
    spam = "spam"


class PaymentType(str, Enum):
    cash = "cash"
    gifting = "gifting"
    affiliate = "affiliate"
    none = "none"
    unclear = "unclear"


class Action(str, Enum):
    accept = "accept"
    negotiate = "negotiate"
    ask_for_details = "ask_for_details"
    decline = "decline"
    ignore_or_report = "ignore_or_report"


class Platform(str, Enum):
    instagram = "instagram"
    youtube = "youtube"
    tiktok = "tiktok"
    x = "x"
    linkedin = "linkedin"
    facebook = "facebook"
    blog = "blog"
    podcast = "podcast"
    other = "other"


class Kind(str, Enum):
    reel = "reel"
    story = "story"
    post = "post"
    carousel = "carousel"
    video = "video"
    short = "short"
    livestream = "livestream"
    integration = "integration"
    article = "article"
    other = "other"


# ---------- input models (plain code builds these) ----------

class Email(BaseModel):
    id: str
    sender: str
    subject: str
    date: Optional[str] = None
    body: str


class Exclusivity(BaseModel):
    category: str
    brands: list[str] = []
    until: Optional[str] = None       # ISO date; None = open-ended


class CreatorProfile(BaseModel):
    name: str = "Creator"
    currency: str = "INR"
    rates: dict[str, float] = {}      # "instagram:reel" -> 8000
    exclusivities: list[Exclusivity] = []
    avoid_categories: list[str] = []  # e.g. ["gambling", "alcohol"]
    rules_text: list[str] = []        # free-text content rules
    accepts_gifting: bool = False
    min_lead_days: int = 3
    raw: dict = {}


# ---------- what Gemini returns (no defaults: required for structured output) ----------

class Deliverable(BaseModel):
    platform: Platform
    kind: Kind
    quantity: int = Field(description="How many of this deliverable. Use 1 if not stated.")


class EmailExtraction(BaseModel):
    category: Category
    category_reason: str = Field(description="One or two plain sentences explaining the category.")
    brand: Optional[str] = Field(description="The brand the work is FOR (not the agency).")
    agency: Optional[str] = Field(description="Agency or PR firm writing on the brand's behalf, if any.")
    contact_name: Optional[str]
    contact_email: Optional[str]
    mentions_earlier_message: bool = Field(
        description="True if this is a follow-up, reminder or reply about an earlier message or offer.")
    deliverables: list[Deliverable]
    fee: Optional[float] = Field(description="TOTAL cash amount offered for all deliverables, as a number.")
    currency: Optional[str] = Field(description="ISO code such as INR or USD.")
    payment_type: PaymentType
    deadline: Optional[str] = Field(description="Posting or delivery deadline as YYYY-MM-DD, or null.")
    usage_rights: Optional[str] = Field(description="What the brand may do with the content, quoted briefly. Null if not stated.")
    exclusivity_requested: Optional[str] = Field(description="Exclusivity the brand asks the creator to agree to, if any.")
    product_category: Optional[str] = Field(description="What the product is, e.g. 'skincare', 'mobile game'.")
    matches_exclusivity_categories: list[str] = Field(
        description="Items from the creator's exclusivity list that this product falls into. Copy them exactly. Empty if none.")
    matches_avoid_categories: list[str] = Field(
        description="Items from the creator's avoid list that this product falls into. Copy them exactly. Empty if none.")
    other_rule_concerns: list[str] = Field(
        description="Other creator content rules this offer may break, each as one short sentence.")
    suspicious_signals: list[str] = Field(description="Anything suspicious, each as one short sentence.")
    missing_info: list[str]
    notes: Optional[str]

    @classmethod
    def empty(cls) -> "EmailExtraction":
        return cls(category=Category.needs_more_info, category_reason="", brand=None, agency=None,
                   contact_name=None, contact_email=None, mentions_earlier_message=False, deliverables=[],
                   fee=None, currency=None, payment_type=PaymentType.unclear, deadline=None,
                   usage_rights=None, exclusivity_requested=None, product_category=None,
                   matches_exclusivity_categories=[], matches_avoid_categories=[], other_rule_concerns=[],
                   suspicious_signals=[], missing_info=[], notes=None)


class ReplyDraft(BaseModel):
    subject: str
    body: str


# ---------- output models ----------

class RiskFlag(BaseModel):
    code: str
    severity: str          # low | medium | high
    reason: str


class EmailResult(BaseModel):
    email_id: str
    sender: str
    subject: str
    date: Optional[str]
    category: Category
    category_reason: str
    llm_category: Optional[Category] = None
    scam_signals: list[str] = []
    error: Optional[str] = None
    deal_id: Optional[str] = None
    extraction: Optional[EmailExtraction] = None


class Deal(BaseModel):
    deal_id: str
    email_ids: list[str]
    category: Category
    headline: str
    brand: Optional[str]
    agency: Optional[str]
    contact_name: Optional[str]
    contact_email: Optional[str]
    deliverables: list[Deliverable]
    fee: Optional[float]
    currency: Optional[str]
    payment_type: PaymentType
    deadline: Optional[str]
    usage_rights: Optional[str]
    exclusivity_requested: Optional[str]
    product_category: Optional[str]
    missing_info: list[str]
    risk_flags: list[RiskFlag]
    recommended_action: Action
    reply_draft: Optional[ReplyDraft] = None
    
class BatchItem(EmailExtraction):
    """One result inside a batched model response: an extraction plus the id of its email."""
    email_id: str


class BatchExtraction(BaseModel):
    results: list[BatchItem]


class ReplyDraft(BaseModel):
    subject: str
    body: str


class DraftItem(ReplyDraft):
    deal_id: str


class BatchDrafts(BaseModel):
    drafts: list[DraftItem]