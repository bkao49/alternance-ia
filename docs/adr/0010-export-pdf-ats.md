# ADR 0010 : export PDF lisible par les logiciels de recrutement

Statut : proposé (2026-11-01)

## Décision
- Bibliothèque : **ReportLab** (BSD, Python pur), et non WeasyPrint prévu par l'issue #23 : WeasyPrint exige Pango et Cairo dans l'image Docker (plus grosse, plus de surface d'attaque, plus de mises à jour système), alors que le besoin est un texte simple sur une colonne. Le rendu HTML → PDF n'apporte rien ici.
- Mise en page : une colonne A4, Helvetica et Helvetica-Gras (polices standard, non incorporées), tirets en texte pour les lignes du CV, paragraphes pour la lettre. Aucune image, aucun tableau, aucune icône, aucun lien.
- Texte : réduit à l'alphabet Windows-1252 (celui des polices standard) ; les flèches et symboles courants deviennent des équivalents (`->`, `>=`), le reste perd son accent ou devient `?`. Un CV en caractères non latins n'est donc pas géré (hors périmètre : profil francophone).
- Métadonnées : seulement le titre. Auteur, créateur, logiciel et sujet vides ; date fixe (`invariant`), donc un même contenu donne le même fichier.
- Garde-fou : `GET /documents/{id}/pdf` refuse (409 `check_failed`) tant que le contrôle factuel déterministe de la version courante n'est pas vert. L'export n'envoie rien et ne change le statut d'aucune candidature.
- Test : le texte extrait du PDF avec `pypdf` est comparé au texte source (accents, guillemets, ligne très longue, ordre de lecture).
