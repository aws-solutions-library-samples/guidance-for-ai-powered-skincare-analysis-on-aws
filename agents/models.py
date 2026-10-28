"""Pydantic models for structured output across all skincare agents."""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from .search.contracts import Identifier, Preferences


class SkinMetrics(BaseModel):
    """Numeric skin metrics scored independently using clinical criteria (0-100)."""

    skin_health: int = Field(
        ge=0, le=100,
        description="Composite barrier integrity, inflammation, lesion count. 85-100=clear/strong, 60-84=minor issues, 40-59=multiple concerns, 0-39=significant issues"
    )
    hydration: int = Field(
        ge=0, le=100,
        description="Transepidermal water loss signs. 85-100=plump/dewy, 60-84=minor dry areas, 40-59=tightness/flaking, 0-39=cracking/papery"
    )
    texture: int = Field(
        ge=0, le=100,
        description="Surface smoothness and regularity. 85-100=glass-smooth, 60-84=localized texture, 40-59=noticeable roughness, 0-39=scarring"
    )
    pore_size: int = Field(
        ge=0, le=100,
        description="Pore visibility and refinement. 85-100=barely visible, 60-84=small/slightly visible, 40-59=clearly visible, 0-39=significantly enlarged"
    )
    elasticity: int = Field(
        ge=0, le=100,
        description="Firmness and structural integrity. 85-100=firm/sharp contours, 60-84=early laxity, 40-59=noticeable laxity, 0-39=significant sagging"
    )
    radiance: int = Field(
        ge=0, le=100,
        description="Luminosity and light reflection. 85-100=visibly luminous, 60-84=bright with dull patches, 40-59=flat/matte, 0-39=sallow/ashen"
    )


class SkinProfile(BaseModel):
    """Structured skin analysis result from image analysis."""

    skin_type: str = Field(
        description="Skin type: Combination, Oily, Dry, Normal, or Sensitive"
    )
    age: str = Field(description="Age range: 18-24, 25-32, 33-40, 41-50, or 50+")
    concerns: list[str] = Field(description="List of 2-4 specific skin concerns")
    current_condition: str = Field(
        description="Brief assessment of current skin condition"
    )
    recommended_goals: str = Field(description="Recommended skincare goals")
    skin_metrics: SkinMetrics = Field(
        description="Numeric skin metrics for radar chart visualization"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="List of 2-4 positive skin attributes (e.g. 'Even skin tone', 'Good elasticity')",
    )


class RoutineStep(BaseModel):
    """A single step in the skincare routine."""

    step_name: str = Field(
        min_length=1,
        description="Step name matching a product type in the database"
    )
    justification: str = Field(description="Why this step is needed for this user")
    why_this_step_for_you: str = Field(
        description="Personalized explanation for the user"
    )
    when: Literal["Morning", "Evening", "Morning & Evening"]


class UserProfile(BaseModel):
    """Extracted user profile from skin analysis."""

    skin_type: str
    age: str
    concerns: list[str]
    routine_rationale: str = Field(
        description="2-3 sentences explaining the routine design"
    )


class RoutineSummary(BaseModel):
    """Summary of the routine."""

    total_steps: int = Field(ge=2, le=8)
    benefits: list[str]
    usage_notes: list[str]


class StepAnalysisResult(BaseModel):
    """Structured output from step analysis agent."""

    user_profile: UserProfile
    routine_steps: list[RoutineStep] = Field(min_length=2, max_length=8)
    routine_summary: RoutineSummary

    @model_validator(mode="after")
    def validate_steps(self) -> Self:
        names = [step.step_name for step in self.routine_steps]
        if len(set(names)) != len(names):
            raise ValueError("Routine step names must be unique")
        if self.routine_summary.total_steps != len(names):
            raise ValueError("routine_summary.total_steps must match routine_steps")
        return self


# --- New models for Graph node outputs ---


class IngredientDetail(BaseModel):
    """A single ingredient recommendation with personalized context."""

    ingredient_id: Identifier = Field(description="Canonical ingredient ID returned by an ingredient tool")
    name: str = Field(description="Display name of that exact ingredient identity")
    benefit: str = Field(min_length=1, description="Primary benefit/function")
    why_for_you: str = Field(description="Personalized explanation for this user")
    usage: str = Field(description="Concentration, frequency, and usage notes")

    @field_validator("benefit")
    @classmethod
    def benefit_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ingredient benefit must not be blank")
        return value


class IngredientsAnalysisOutput(BaseModel):
    """Structured output from an ingredients analysis agent node."""

    step_name: str
    key_ingredients: list[IngredientDetail] = Field(min_length=1, max_length=5)
    analysis_notes: str = Field(
        description="Why these ingredients work together for this user"
    )


class ProductDetail(BaseModel):
    """A single product recommendation with match details."""

    product_id: str = Field(min_length=1, max_length=128, description="Exact stable product_id from this step's catalog tool result")
    name: str = Field(description="Product name from database")
    price: str = Field(description="Formatted price with currency")
    match_score: str = Field(description="Ingredient match percentage")
    image_url: str = Field(
        default="",
        description="Exact image URL from the database tool results. MUST be copied verbatim.",
    )
    matched_ingredients: list[str] = Field(default_factory=list)
    matched_ingredient_ids: list[str] = Field(default_factory=list)
    matched_must_have_ingredient_ids: list[str] = Field(default_factory=list)
    matched_count: int = Field(default=0, ge=0, le=5)
    preferred_count: int = Field(default=0, ge=0, le=5)
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    why_for_you: str = Field(description="Personalized product recommendation")
    usage_tip: str = Field(description="Usage tip for this user's skin type")


class ProductAnalysisOutput(BaseModel):
    """Structured output from a product recommendation agent node."""

    step_name: str
    status: Literal["matched", "no_match"] = "matched"
    reason: Literal["no_matching_products", "catalog_changed"] | None = None
    top_recommendations: list[ProductDetail] = Field(max_length=3)

    @model_validator(mode="after")
    def valid_outcome(self) -> Self:
        if self.status == "matched" and (not self.top_recommendations or self.reason):
            raise ValueError("Matched product output needs products and no reason")
        if self.status == "no_match" and (self.top_recommendations or not self.reason):
            raise ValueError("No-match output needs an explicit reason and no products")
        return self


class ProductExplanation(BaseModel):
    product_id: str = Field(min_length=1, max_length=128)
    why_for_you: str = Field(min_length=1, max_length=1500)
    usage_tip: str = Field(min_length=1, max_length=1000)

    @field_validator("why_for_you", "usage_tip")
    @classmethod
    def explanation_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Product explanation text must not be blank")
        return value


class ProductExplanations(BaseModel):
    step_name: str
    products: list[ProductExplanation] = Field(min_length=1, max_length=3)


class CompiledStep(BaseModel):
    """A fully compiled routine step with ingredients and products."""

    step_name: str
    when: str
    description: str
    why_for_you: str
    ingredients: list[IngredientDetail]
    products: list[ProductDetail]
    recommendation_status: Literal["matched", "no_match"] = "matched"
    no_match_reason: Literal["no_matching_products", "catalog_changed"] | None = None


class CompiledRoutine(BaseModel):
    """Final compiled routine — deterministic output from CompileNode."""

    user_profile: UserProfile
    routine_steps: list[CompiledStep]
    api_version: Literal[1, 2] = 1
    applied_preferences: Preferences = Field(default_factory=Preferences)
