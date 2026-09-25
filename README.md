# Agenda automatique de Nyons

Ce mini-site GitHub Pages affiche l'agenda de Nyons **semaine par semaine** et met à jour ses données automatiquement depuis l'agenda public de la Ville de Nyons.

## Fichiers

- `index.html` : page visible par les lecteurs, responsive mobile.
- `agenda.json` : données affichées par la page.
- `update_agenda.py` : récupère les événements depuis nyons.com.
- `requirements.txt` : dépendances Python.
- `.github/workflows/update-agenda.yml` : mise à jour automatique toutes les 3 heures.

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
