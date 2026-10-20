# Encadrés spectateurs — dès le 20 octobre 2026

Validation de la généralisation reçue le 20 octobre 2026. Le pilote Fausse Note
est effectivement publié, sous le petit mot de Papy, avec canonical propre et
index,follow. La lecture initiale via moteur de recherche était périmée ; le
contrôle direct du navigateur a confirmé la version publiée.

## Périmètre et fonctionnement

cinema_agenda.py appelle déjà render_spectator_reviews pour chaque film.
cinema_reviews.py rend maintenant 2–3 paragraphes originaux depuis le cache
cinema-spectator-reviews.json pour toute fiche de type cinéma contenant au moins
une séance réelle datée du 20 octobre 2026 ou après. La date de début de la fiche
ne décide pas de l’éligibilité. Les fiches dont toutes les séances sont antérieures
restent sans encadré. Le même mécanisme couvre les futurs programmes sans nouvelle
liste d’URL ni changement de template.

Le titre ET l’affiche doivent correspondre à l’identité du film vérifié ; une
reprogrammation du même film réutilise la synthèse. Un autre film homonyme ou une
nouvelle affiche exige une vérification avant ajout au cache. Sans preuve, source,
date, validation éditoriale ou texte nuancé, aucun encadré. Une erreur de cache
masque l’encadré sans interrompre la génération des séances.

HTML statique, aucun JavaScript supplémentaire, aucune requête externe, aucun
appel OpenAI. Le cache est lu une fois par processus et invalidé lorsqu’il change.
Les contenus existants, séances, affiches, réservations, canonical, données
structurées et liens ne sont pas modifiés. Aucun DNS, redirect ou alias modifié.

## Sources et vérification éditoriale

Cache du pilote réutilisé ; deux consultations éditoriales ponctuelles ajoutées :

- Cars (2006), AlloCiné 55774 :
  https://www.allocine.fr/film/fichefilm-55774/critiques/spectateurs/
- Mary et la fleur de la sorcière (2017), AlloCiné 252533 :
  https://www.allocine.fr/film/fichefilm-252533/critiques/spectateurs/recentes/

Les noms, dates et observations courtes de contrôle sont consignés dans le cache ;
chaque point renvoie aux observations qui l’étayent. Il s’agit de synthèses
éditoriales originales de thèmes, sans extrait copié, faux témoignage, note
agrégée, spoiler ou affirmation d’un achat de billet vérifié. Les avis consultés
ne représentent pas nécessairement l’ensemble des spectateurs. Aucune extraction
de corpus, pagination, collecte récurrente ou import automatisé AlloCiné.

Au 20 octobre : 37 fiches éligibles sur 55, dont 31 du nouveau programme.
Trois fiches ont une synthèse validée (Fausse Note, Cars, Mary) ; les 34 autres
restent sans encadré. Une absence signifie qu’aucune synthèse n’est validée dans
notre cache, et non qu’aucun avis n’existe ailleurs.

## Ajouts ultérieurs

Vérifier d’abord le cache. Pour chaque ajout : confirmer le film exact, consulter
ponctuellement des avis authentiques, consigner sources/dates/observations,
écrire 2–3 points fidèles et nuancés sans révélation de l’intrigue, puis valider
le statut editorially_verified. Ne jamais déduire un avis du synopsis ou inventer
une réserve pour équilibrer artificiellement. Si les éléments manquent, omettre.

La publication automatique réutilise ces validations ; elle ne recherche pas
d’avis. Une collecte à grande échelle nécessiterait un fournisseur dont les droits
autorisent explicitement l’accès, la réutilisation et l’automatisation, ou des avis
directs de lecteurs avec accord approprié. Aucune source de ce type n’est
actuellement connectée. Une page publique ou robots.txt n’est pas une licence.
