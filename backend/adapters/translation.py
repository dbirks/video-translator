"""Translation adapters: Protocol + LLM implementation (stubbed for POC)."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TranslationAdapter(Protocol):
    async def translate(self, text: str, source_lang: str = "en", target_lang: str = "es") -> str:
        """Translate text from source_lang to target_lang."""
        ...


class LLMTranslationAdapter:
    """
    Translation adapter backed by an LLM (Mistral/OpenAI).

    For the POC, this returns mock Spanish translations so the pipeline can
    run end-to-end without a real API key. Replace the body of translate()
    with real API calls when ready.
    """

    def __init__(self, api_key: str | None = None, model: str = "mistral-large-latest"):
        self.api_key = api_key
        self.model = model

    async def translate(self, text: str, source_lang: str = "en", target_lang: str = "es") -> str:
        """Return a mock Spanish translation."""
        # Simple mock mapping for common phrases
        mock_translations: dict[str, str] = {
            "Welcome to this lecture on machine learning fundamentals.":
                "Bienvenidos a esta conferencia sobre los fundamentos del aprendizaje automático.",
            "Today we will cover the basics of neural networks and deep learning.":
                "Hoy cubriremos los conceptos básicos de las redes neuronales y el aprendizaje profundo.",
            "A neural network consists of layers of interconnected nodes.":
                "Una red neuronal consiste en capas de nodos interconectados.",
            "Each node applies an activation function to its inputs.":
                "Cada nodo aplica una función de activación a sus entradas.",
            "Training involves adjusting weights to minimize a loss function.":
                "El entrenamiento implica ajustar los pesos para minimizar una función de pérdida.",
            "Backpropagation is the algorithm used to compute gradients.":
                "La retropropagación es el algoritmo utilizado para calcular los gradientes.",
            "Gradient descent updates the weights in the direction of steepest descent.":
                "El descenso de gradiente actualiza los pesos en la dirección de mayor descenso.",
        }

        if text in mock_translations:
            return mock_translations[text]

        # Generic mock: prepend "[ES]" and append a Spanish filler
        words = text.split()
        mock = " ".join(words)  # keep same words as placeholder
        return f"[Traducción de: {mock}]"
