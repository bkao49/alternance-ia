"""Pseudonymisation avant tout envoi : nom, e-mail, téléphone, adresse.

Chaque valeur est remplacée par un jeton stable dans l'appel (« [EMAIL_1] »). La table de
correspondance reste en mémoire, le temps de l'appel, pour remettre les valeurs dans la réponse.
C'est un filet de sécurité par motifs : il ne dispense pas de n'envoyer que le strict nécessaire.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Numéros français (0X ou +33 X, séparateurs espace, point ou tiret) et internationaux (+CC …).
PHONE = re.compile(
    r"(?<![\w+])(?:(?:\+|00)33[\s.-]?\(?0?\)?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}(?!\d)"
    r"|(?<![\w+])\+\d{1,3}(?:[\s.-]?\d{2,4}){3,5}(?!\d)"
)
STREET_TYPES = (r"rue|avenue|av\.?|boulevard|bd|chemin|all[ée]e|place|impasse|route|quai|cours|"
                r"square|passage|r[ée]sidence|lotissement|villa|cit[ée]|voie")
ADDRESS = re.compile(
    rf"\b\d{{1,4}}(?:\s?(?:bis|ter|quater|[a-d]))?,?\s+(?:{STREET_TYPES})\b[^\n,;]{{0,60}}"
    rf"|\b\d{{5}}\s+[A-ZÀ-Ý][\w'-]+(?:[\s-][A-ZÀ-Ý][\w'-]+)*",
    re.IGNORECASE,
)


@dataclass
class Pseudonymizer:
    """Remplace les noms connus (fournis par l'appelant) puis les motifs e-mail, téléphone, adresse."""

    known_names: Iterable[str] = ()
    mapping: dict[str, str] = field(default_factory=dict)  # jeton -> valeur d'origine
    _counts: dict[str, int] = field(default_factory=dict)

    def _token(self, kind: str, value: str) -> str:
        for token, original in self.mapping.items():
            if original == value and token.startswith(f"[{kind}_"):
                return token
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[{kind}_{self._counts[kind]}]"
        self.mapping[token] = value
        return token

    def apply(self, text: str) -> str:
        # Les e-mails d'abord (ils contiennent souvent le nom), puis les noms, les plus longs d'abord :
        # « Jeanne Martin » avant « Jeanne ».
        text = EMAIL.sub(lambda m: self._token("EMAIL", m.group(0)), text)
        names = sorted({n.strip() for n in self.known_names if len(n.strip()) >= 2}, key=len, reverse=True)
        for name in names:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)",
                          lambda m: self._token("NOM", m.group(0)), text, flags=re.IGNORECASE)
        for kind, pattern in (("TEL", PHONE), ("ADRESSE", ADDRESS)):
            text = pattern.sub(lambda m, k=kind: self._token(k, m.group(0)), text)
        return text

    def restore(self, text: str) -> str:
        for token, original in self.mapping.items():
            text = text.replace(token, original)
        return text
