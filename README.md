# Agenda automatique de Nyons

Ce mini-site GitHub Pages affiche l'agenda de Nyons **semaine par semaine** et met à jour ses données automatiquement depuis l'agenda public de la Ville de Nyons.

## Fichiers

- `index.html` : page visible par les lecteurs, responsive mobile.
- `agenda.json` : données affichées par la page.
- `update_agenda.py` : récupère les événements depuis nyons.com.
- `requirements.txt` : dépendances Python.
- `.github/workflows/update-agenda.yml` : mise à jour automatique chaque jour à 06 h 17 UTC.

## Installation rapide sur GitHub

1. Créer un dépôt public, par exemple `agenda-nyons`.
2. Envoyer **tout le contenu de ce dossier**, y compris le dossier caché `.github`.
3. Aller dans `Settings > Pages`.
4. `Source` : **Deploy from a branch**.
5. `Branch` : **main**, dossier **/(root)**, puis `Save`.
6. Aller dans `Actions > Mise a jour agenda Nyons > Run workflow` pour lancer une première mise à jour manuelle.

Le site sera ensuite disponible à une adresse du type :
`https://VOTRE-COMPTE.github.io/agenda-nyons/`

## Autoriser l'Action à écrire si nécessaire

Si l'Action échoue au moment du `git push` :
`Settings > Actions > General > Workflow permissions > Read and write permissions > Save`.

## Intégration Blogger

Une fois la page GitHub Pages publiée, insérer dans Blogger en mode HTML :

```html
<iframe
  src="https://VOTRE-COMPTE.github.io/agenda-nyons/"
  style="width:100%;height:900px;border:0;overflow:hidden;"
  loading="lazy"
  title="Agenda de Nyons">
</iframe>
```

Pour une page Blogger dédiée, une hauteur de 900 à 1200 px convient généralement. La page GitHub est responsive et s'adapte au téléphone.

## Source et prudence

Source affichée : Ville de Nyons — agenda officiel.
Le script reste volontairement léger, ne contourne aucune connexion et ne reproduit que les informations utiles de la liste avec un lien vers la fiche officielle.


## Cinéma L’Arlequin

`cinema-programme.json` contient les films, affiches et séances explicites du PDF officiel. `cinema_agenda.py` génère une fiche et un calendrier par film ainsi que `/cinema/`. Les VF/VO sont regroupées, jamais présentées comme un spectacle quotidien entre deux dates. Une fiche municipale existante est réutilisée lorsqu’elle correspond au même film et à la même séance.

La mise à jour quotidienne conserve cette source distincte et ne réécrit pas les fiches cinéma avec les textes municipaux. Les films terminés quittent la sélection actuelle, leurs pages datées restent consultables.

Une automatisation Codex rattachée au chat contrôle le programme à partir du lendemain de sa dernière date, soit le 21 octobre 2026 pour le programme du 30 septembre au 20 octobre. Elle ouvre cinema-arlequin.fr, récupère le PDF courant, vérifie ses dates et renouvelle les séances futures et les affiches. Si le nouveau PDF n’est pas encore disponible, elle réessaie le lendemain sans inventer de séances. Après chaque renouvellement, `next_check_date` prend la date de fin du nouveau programme plus un jour. Elle publie les données et pages sur GitHub et vérifie le résultat. Les titres comportent le nom du film, Nyons et les horaires au cinéma L’Arlequin ; les textes courts gardent le ton simple de Papy.

## Nyons aujourd’hui

La page /aujourdhui/ réutilise agenda.json et cinema-programme.json, et renvoie vers les fiches déjà présentes. Le bouton « NYONS AUJOURD’HUI » figure en haut de l’accueil. Les liens « Demain » et « Ce week-end » filtrent réellement les événements et les séances, sans nouvelles fiches.

La date se calcule dans le fuseau Europe/Paris, y compris après minuit et lors des changements d’heure. Les séances utilisent leurs dates explicites ; les séances passées de la journée restent visibles avec cette mention. Les événements sur plusieurs jours sont inclus pendant leur période, avec invitation à vérifier leurs horaires dans la fiche.

build_today.py génère une sélection HTML lisible sans JavaScript pour les moteurs de recherche. La mise à jour quotidienne existante l’exécute après les autres générateurs et conserve /aujourdhui/ dans le sitemap. Le navigateur actualise la sélection depuis les JSON existants dès l’ouverture, au changement de journée et toutes les 30 minutes. Les données du cinéma restent dépendantes du renouvellement de son programme existant.

Météo : service gratuit wttr.in (et son domaine équivalent wttr.is), format JSON j1, coordonnées de Nyons 44.36, 5.14. Température et vent correspondent à la dernière observation du jour ; mini/maxi et pluie sont les prévisions journalières. Les données sont conservées 30 minutes dans le navigateur. En cas d’échec, un instantané généré par le workflow est utilisable pendant six heures ; ensuite un message d’indisponibilité s’affiche. Une panne météo ne bloque jamais l’agenda.

Le module n’importe aucun générateur d’événement et n’appelle jamais OpenAI. Les scripts et caches éditoriaux existants sont conservés. Aucun rafraîchissement supplémentaire du workflow payant n’est lancé pour publier ce module.

Vérification indépendante (aucune API payante, aucun secret) : workflow check-today.yml, tests Python et Node sur dates Paris, week-end, intervalles, séances explicites, liens existants, météo manquante, génération répétée et conservation des données.
