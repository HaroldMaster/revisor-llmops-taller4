import hashlib
import os

os.environ["REVISOR_LANGFUSE"] = "0"  # antes de importar el revisor: los tests no envían spans
from pathlib import Path

import numpy as np
import pytest

from revisor.perfil import cargar_perfil

REPO_PRUEBA = Path(__file__).resolve().parent.parent / "repo-prueba"


class EmbeddingsFalsos:
    """Vector de bolsa de palabras: sin red y determinista."""

    model = "falso"
    DIMENSION = 256

    def _vector(self, texto: str) -> list[float]:
        vector = np.zeros(self.DIMENSION)
        for palabra in texto.lower().split():
            indice = int(hashlib.md5(palabra.encode()).hexdigest(), 16) % self.DIMENSION
            vector[indice] += 1
        return vector.tolist()

    def embed_documents(self, textos):
        return [self._vector(t) for t in textos]

    def embed_query(self, texto):
        return self._vector(texto)


@pytest.fixture(scope="session")
def perfil():
    return cargar_perfil(REPO_PRUEBA)


@pytest.fixture(scope="session")
def embeddings():
    return EmbeddingsFalsos()
