"""
Utilitários de I/O com Supabase Storage para o mesh-service.

Funções compartilhadas entre os routers de análise e execução de corte.
"""

import logging
import tempfile
from pathlib import Path

import httpx
from supabase import Client

logger = logging.getLogger(__name__)


def create_download_url(supabase: Client, storage_path: str, expires_in: int = 300) -> str:
    """Gera URL assinada de download do Supabase Storage (bucket 'models')."""
    response = supabase.storage.from_("models").create_signed_url(
        path=storage_path,
        expires_in=expires_in,
    )
    # supabase-py 2.x retorna dict com 'signedURL'
    if not response or "signedURL" not in response:
        raise RuntimeError(f"Falha ao gerar URL de download: {response}")
    return str(response["signedURL"])


async def download_to_tempfile(url: str, storage_path: str) -> str:
    """
    Baixa o arquivo da URL assinada para um arquivo temporário.

    Args:
        url: URL assinada de download.
        storage_path: Caminho original no Storage (usado apenas para inferir a extensão).

    Returns:
        Caminho absoluto do arquivo temporário criado. Lembre-se de deletar após o uso.
    """
    suffix = Path(storage_path).suffix or ".stl"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with Path(tmp_path).open("wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    logger.info("Download concluído: %s → %s", storage_path, tmp_path)
    return tmp_path


def upload_bytes(
    supabase: Client,
    storage_path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """
    Faz upload de bytes para o bucket 'models' no Supabase Storage.

    supabase-py v2: storage.upload() aceita bytes diretamente, mas NÃO BytesIO.
    Usa upsert=True para sobrescrever se já existir (re-execução de sessão).
    """
    supabase.storage.from_("models").upload(
        path=storage_path,
        file=data,  # bytes puro — BytesIO NÃO é suportado no supabase-py v2
        file_options={
            "content-type": content_type,
            "upsert": "true",  # header HTTP deve ser string, não bool
        },
    )
    logger.info("Upload concluído: %s (%d bytes)", storage_path, len(data))

