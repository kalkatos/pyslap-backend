from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Security Secrets
    secret_key: str = "pyslap_default_secret_key_32_bytes_min"
    external_secret: str = "pyslap_default_external_secret_32_bytes_min"
    
    # Guest Configuration
    guest_allowed: bool = True
    guest_lifetime_sec: int = 86400  # 24 hours
    guest_id_prefix: str = "anon_"
    session_token_ttl: int = 3600  # 1 hour
    
    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }


# Singleton instance
settings = Settings()
