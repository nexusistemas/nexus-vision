"""
Pós-processamento e heurística inteligente para placas brasileiras (Mercosul e Antiga).
Limpa ruídos do OCR, aplica correções posicionais por slot e valida via Regex estrito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

# Padrão oficial brasileiro:
# - Antiga:   LLLNNNN  (ex: ABC1234)
# - Mercosul: LLLNLNN  (ex: ABC1D23)
BR_PLATE_REGEX = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")

# Posições 0, 1, 2 (sempre letras)
DIGIT_TO_LETTER: dict[str, str] = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "4": "A",
    "5": "S",
    "6": "G",
    "7": "T",
    "8": "B",
}

# Posições 3, 5, 6 (sempre números)
LETTER_TO_DIGIT: dict[str, str] = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "S": "5",
    "G": "6",
    "T": "7",
    "B": "8",
}

# Prefixo comum lido acidentalmente da faixa azul Mercosul
_HEADER_PREFIXES = ("BRASIL", "BRA", "BR")


@dataclass(frozen=True)
class ValidatedPlate:
    """Resultado validado de uma leitura ALPR no padrão brasileiro."""

    plate: str
    raw_text: str
    pattern: str  # "MERCOSUL" ou "ANTIGA"
    confidence: float
    corrections: int


def clean_ocr_text(raw_text: str) -> str:
    """Remove espaços, hífens, pontuação e caracteres fora de A-Z / 0-9."""
    if not raw_text:
        return ""
    return re.sub(r"[^A-Z0-9]", "", raw_text.upper())


def _correct_7char_candidate(
    candidate: str,
    char_confidences: Optional[Sequence[float]] = None,
) -> Optional[tuple[str, int]]:
    """
    Aplica heurística posicional em um candidato de exatamente 7 caracteres.
    Retorna (placa_corrigida, qtd_correcoes) ou None se inválido.
    """
    if len(candidate) != 7:
        return None

    chars = list(candidate)
    corrections = 0

    # Posições 0, 1, 2 -> SEMPRE LETRAS
    for idx in (0, 1, 2):
        ch = chars[idx]
        if ch.isdigit():
            mapped = DIGIT_TO_LETTER.get(ch)
            if not mapped:
                return None
            chars[idx] = mapped
            corrections += 1
        elif not ("A" <= ch <= "Z"):
            return None

    # Posição 3 -> SEMPRE NÚMERO
    ch3 = chars[3]
    if ch3.isalpha():
        mapped = LETTER_TO_DIGIT.get(ch3)
        if not mapped:
            return None
        chars[3] = mapped
        corrections += 1
    elif not ch3.isdigit():
        return None

    # Posição 4 -> HÍBRIDA (Letra na Mercosul ou Número na Antiga)
    ch4 = chars[4]
    if not (ch4.isdigit() or ("A" <= ch4 <= "Z")):
        return None
    # Nota: em placas Mercosul brasileiras, a 5ª posição usa A-J (mapeada de 0-9).
    # Se o OCR tiver confiança muito baixa em um caractere que não pertence a [0-9A-J]
    # mas tem equivalente numérico direto (ex: Q/O->0, L->1, Z->2, S->5), normaliza para dígito.
    if ch4.isalpha() and ch4 not in "ABCDEFGHIJ":
        c4_conf = (
            float(char_confidences[4])
            if char_confidences is not None and len(char_confidences) == 7
            else 1.0
        )
        if c4_conf < 0.72 and ch4 in LETTER_TO_DIGIT:
            chars[4] = LETTER_TO_DIGIT[ch4]
            corrections += 1

    # Posições 5 e 6 -> SEMPRE NÚMEROS
    for idx in (5, 6):
        ch = chars[idx]
        if ch.isalpha():
            mapped = LETTER_TO_DIGIT.get(ch)
            if not mapped:
                return None
            chars[idx] = mapped
            corrections += 1
        elif not ch.isdigit():
            return None

    final_plate = "".join(chars)
    if not BR_PLATE_REGEX.match(final_plate):
        return None

    # Descarta artefatos degenerados (ex: todos os 3 primeiros iguais + todos dígitos iguais como OOO0000)
    if len(set(final_plate)) <= 2:
        return None

    return final_plate, corrections


def validate_brazilian_plate(
    raw_text: str,
    confidence: float = 1.0,
    char_confidences: Optional[Sequence[float]] = None,
) -> Optional[ValidatedPlate]:
    """
    Limpa, corrige posicionalmente e valida uma string OCR nos dois padrões do Brasil.
    Retorna ValidatedPlate ou None se for texto inválido / parcial / ruído.
    """
    cleaned = clean_ocr_text(raw_text)
    if len(cleaned) < 7 or len(cleaned) > 13:
        return None

    candidates: list[tuple[str, Optional[Sequence[float]]]] = []

    if len(cleaned) == 7:
        candidates.append((cleaned, char_confidences))
    else:
        # 1) Tenta remover prefixo da faixa azul ("BR", "BRA", "BRASIL")
        stripped = cleaned
        for pref in _HEADER_PREFIXES:
            if stripped.startswith(pref) and len(stripped) - len(pref) >= 7:
                sub = stripped[len(pref) :]
                if len(sub) == 7:
                    candidates.append((sub, None))
                else:
                    candidates.append((sub[:7], None))
                    candidates.append((sub[-7:], None))
                break

        # 2) Janela deslizante de 7 caracteres para ignorar ruído lateral de parafuso/borda
        for start in range(0, len(cleaned) - 6):
            window = cleaned[start : start + 7]
            if all(w != window for w, _ in candidates):
                candidates.append((window, None))

    best: Optional[tuple[str, int]] = None
    max_allowed_corrections = 3 if confidence >= 0.70 else 2

    for cand, c_confs in candidates:
        res = _correct_7char_candidate(cand, c_confs)
        if res is None:
            continue
        plate, corr = res
        if corr > max_allowed_corrections:
            continue
        if best is None or corr < best[1]:
            best = (plate, corr)
            if corr == 0:
                break

    if best is None:
        return None

    plate, corr = best
    pattern = "MERCOSUL" if plate[4].isalpha() else "ANTIGA"
    # Penaliza levemente confiança se houve múltiplas correções posicionais
    adjusted_conf = max(0.0, min(1.0, float(confidence) - (corr * 0.03)))

    return ValidatedPlate(
        plate=plate,
        raw_text=raw_text,
        pattern=pattern,
        confidence=adjusted_conf,
        corrections=corr,
    )
