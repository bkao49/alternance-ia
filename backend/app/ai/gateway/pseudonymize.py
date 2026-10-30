"""Pseudonymisation avant tout envoi : e-mail, URL, nom, date de naissance, téléphone, adresse.

Chaque valeur est remplacée par un jeton stable dans l'appel (« [EMAIL_1_3fa9c2] »). Le suffixe est
tiré du texte d'origine : une annonce ne peut pas deviner un jeton pour se faire rendre une valeur.
La table de correspondance reste en mémoire, le temps de l'appel, pour remettre les valeurs dans la
réponse. C'est un filet de sécurité par motifs : il ne dispense pas de n'envoyer que le strict
nécessaire, et un profil complet (employeurs, dates) reste identifiant.
Tous les motifs sont bornés (pas de répétition illimitée) : aucun texte ne peut les rendre lents.
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

AT = r"(?:@|\s?[\[(]\s?(?:at|arobase)\s?[\])]\s?)"
DOT = r"(?:\.|\s?[\[(]\s?(?:dot|point)\s?[\])]\s?)"
EMAIL = re.compile(rf"(?<![\w.+-])[\w.+-]{{1,64}}{AT}[\w-]{{1,63}}(?:{DOT}[\w-]{{1,63}}){{1,5}}", re.IGNORECASE)
URL = re.compile(r"\b(?:https?://|www\.|(?:linkedin|github|gitlab)\.com/)[^\s<>\"']{1,300}", re.IGNORECASE)
BIRTH = re.compile(r"\bn[ée]e?\s+le\s+\d{1,2}[/.\s-]\d{1,2}[/.\s-]\d{2,4}", re.IGNORECASE)
# Numéros français (0X ou +33 X, séparateurs espace, point ou tiret) et internationaux (+CC …).
PHONE = re.compile(
    r"(?<![\w+])(?:(?:\+|00)33[\s.-]?\(?0?\)?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}(?!\d)"
    r"|(?<![\w+])\+\d{1,3}(?:[\s.-]?\(?\d{1,4}\)?){2,5}(?:[\s.-]?\d{2,4})(?!\d)"
)
STREET = (r"rue|r\.|avenue|av\.?|boulevard|bd|bvd|chemin|ch\.|all[ée]e|place|pl\.|impasse|imp\.|"
          r"route|rte|quai|cours|square|sq\.|passage|r[ée]sidence|lotissement|villa|cit[ée]|"
          r"faubourg|fbg|hameau|lieu-dit|voie|zi|za")
UPPER = r"[A-ZÀ-Ý]"
PROPER = rf"{UPPER}[\w'’-]{{0,30}}"
# Une voie est suivie d'un nom propre (« rue des Lilas », « avenue Jean Jaurès ») : « 1 place disponible »
# ou « 2 cours de formation » ne sont pas des adresses. Code postal + ville en majuscule, même ligne.
ADDRESS = re.compile(
    rf"\b\d{{1,4}}(?:[ \t]?(?:bis|ter|quater|[a-d]))?,?[ \t]+(?i:{STREET})[ \t]+"
    rf"(?:(?i:de|du|des|d'|la|le|les|l')[ \t]?){{0,2}}{PROPER}(?:[ \t-]{PROPER}){{0,3}}"
    rf"|\b(?:BP|CS)[ \t]?\d{{1,5}}\b"
    rf"|\b\d{{5}}\b[ \t]+{PROPER}(?:[ \t-]{PROPER}){{0,3}}"
)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def name_variants(names: Iterable[str]) -> set[str]:
    """Nom complet, sans accents, chaque partie d'au moins 3 lettres, initiale + nom (« C. Fictif »)."""
    variants = set()
    for name in names:
        name = " ".join(name.split())
        if len(name) < 2:
            continue
        parts = name.split(" ")
        variants |= {name, *(p for p in parts if len(p) >= 3)}
        if len(parts) >= 2:
            variants.add(f"{parts[0][0]}. {' '.join(parts[1:])}")
    return variants | {strip_accents(v) for v in variants}


@dataclass
class Pseudonymizer:
    known_names: Iterable[str] = ()
    mapping: dict[str, str] = field(default_factory=dict)  # jeton -> valeur d'origine
    _counts: dict[str, int] = field(default_factory=dict)
    salt: str = ""  # fixé par la passerelle à partir du texte complet de l'appel

    def _token(self, kind: str, value: str) -> str:
        for token, original in self.mapping.items():
            if original == value and token.startswith(f"[{kind}_"):
                return token
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[{kind}_{self._counts[kind]}_{self.salt}]"
        self.mapping[token] = value
        return token

    def _sub(self, kind: str, pattern: re.Pattern, text: str) -> str:
        return pattern.sub(lambda m: self._token(kind, m.group(0)), text)

    def apply(self, text: str) -> str:
        if not self.salt:
            self.salt = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:6]
        # E-mails et URL d'abord (ils contiennent souvent le nom), puis les noms, les plus longs d'abord.
        text = self._sub("EMAIL", EMAIL, text)
        text = self._sub("URL", URL, text)
        for name in sorted(name_variants(self.known_names), key=len, reverse=True):
            text = self._sub("NOM", re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE), text)
        for kind, pattern in (("NAISSANCE", BIRTH), ("TEL", PHONE), ("ADRESSE", ADDRESS)):
            text = self._sub(kind, pattern, text)
        return text

    def restore(self, text: str) -> str:
        for token, original in self.mapping.items():
            text = text.replace(token, original)
        return text
