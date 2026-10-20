# Encadré spectateurs — pilote Fausse Note

L'encadré est autorisé uniquement sur :
https://agenda.vivreanyons.fr/evenements/cinema-fausse-note-2026-10-14/

Il suit le petit mot de Papy, avant les horaires. Il est rendu en HTML par
cinema_reviews.py, sans JavaScript, requête externe ou appel à un modèle.

## Vérification éditoriale du 20 octobre 2026
Source : https://www.allocine.fr/film/fichefilm-1000030290/critiques/spectateurs/
Consultation ponctuelle manuelle d'une seule page d'avis publics. Aucun robot de
collecte, import d'avis, citation, note agrégée ou témoignage recomposé.
Les observations de contrôle, auteurs et dates sont consignés dans
cinema-spectator-reviews.json. La synthèse est originale et sans révélation de
l'intrigue. Ces avis publics sont vérifiables ; l'achat d'un billet par leurs
auteurs n'a pas été vérifié.

## Comportement
L'URL exacte et le titre du film doivent correspondre au pilote. Sans fichier
valide, validation éditoriale, texte nuancé ou lien source, aucun encadré.
Ne pas modifier la liste autorisée avant validation explicite de l'utilisateur.
La mise à jour habituelle du cinéma conserve ce module et ses données ; elle
ne collecte aucun avis.

## Extension éventuelle, après validation explicite
Approche prévue : recueillir des avis directement auprès des lecteurs ou des
spectateurs du cinéma, avec accord explicite permettant leur exploitation dans
une synthèse, modération et rattachement vérifié au bon film. Autre possibilité :
un fournisseur ou partenaire dont le contrat autorise explicitement l'accès,
l'usage éditorial et l'automatisation des avis (vérifier ces droits avant
intégration). Aucune source de ce type n'est actuellement connectée.
Ne pas traiter une page publique, un robots.txt ou une API disponible comme une
autorisation de réutilisation à grande échelle. Aucun scraping AlloCiné.
Conserver les sources, dates et contrôle humain de chaque synthèse. Une fiche
sans avis fiables autorisés reste sans encadré. Aucun traitement de masse ni
génération payante ne doit être activé pour cette phase pilote.

