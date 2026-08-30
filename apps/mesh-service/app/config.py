"""Configurações centralizadas do mesh-service via variáveis de ambiente."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações carregadas do arquivo .env ou variáveis de ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Autenticação interna (Next.js → mesh-service)
    python_backend_internal_token: str = ""

    # Ambiente
    app_env: str = "development"

    @property
    def is_production(self) -> bool:
        """Retorna True se o ambiente for produção."""
        return self.app_env.lower() == "production"


# Instância global das configurações — importar em todos os módulos que precisarem
settings = Settings()
