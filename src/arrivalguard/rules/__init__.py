"""rules — karar motoru. Saf fonksiyonlar, yan etkisiz, fixture ile test edilebilir.

Her karar `Explain` listesi üretir: hangi sinyal, hangi değer, hangi ağırlık, hangi kural.
Jüri "neden bu karar?" diye sorduğunda ekranda bu liste gösterilir.
"""
from . import decisions
from .config import Config
from .explain import Decision, Explain

__all__ = ["Explain", "Decision", "Config", "decisions"]
