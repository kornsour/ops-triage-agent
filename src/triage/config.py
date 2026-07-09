"""Central configuration, loaded from environment / .env.

Everything has an offline-safe default so the system runs with zero secrets.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = three levels up from this file (src/triage/config.py).
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIAGE_", env_file=".env", extra="ignore")

    # --- LLM ---
    llm_provider: str = "mock"  # mock | openai | anthropic
    llm_model: str = ""
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # --- Embeddings ---
    embeddings_provider: str = "hashing"  # hashing | openai
    embeddings_dim: int = 256

    # --- Agent loop ---
    max_agent_steps: int = 4  # tool-calling turns before the loop is forced to finish

    # --- Enterprise controls ---
    api_keys: str = "demo-operator-key:operator,demo-admin-key:admin,demo-viewer-key:viewer"
    max_usd_per_run: float = 0.05
    max_latency_ms: int = 15_000
    rate_limit_per_min: int = 60

    # --- Paths ---
    db_path: Path = ROOT / "data" / "triage.db"
    index_dir: Path = ROOT / "data" / "index"
    knowledge_base_dir: Path = ROOT / "knowledge_base"
    audit_path: Path = ROOT / "data" / "audit.log.jsonl"

    def parsed_api_keys(self) -> dict[str, str]:
        """Return {api_key: role}. Roles: viewer | operator | admin."""
        out: dict[str, str] = {}
        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if not pair:
                continue
            key, _, role = pair.partition(":")
            out[key.strip()] = (role.strip() or "viewer")
        return out

    def default_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return {
            "openai": "gpt-4.1",
            "anthropic": "claude-opus-4-8",
            "mock": "mock-1",
        }.get(self.llm_provider, "mock-1")


@lru_cache
def get_settings() -> Settings:
    return Settings()
