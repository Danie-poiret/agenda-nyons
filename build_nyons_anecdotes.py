#!/usr/bin/env python3
"""Construit un catalogue d'histoires locales depuis les sommaires Terre d'Eygues.

Ce script sert uniquement à actualiser manuellement le catalogue. Le site utilise
ensuite le fichier JSON enregistré dans le dépôt, sans solliciter Terre d'Eygues
à chaque mise à jour de l'agenda.
"""

from __future__ import annotations

import json
import hashlib
import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


API_URL = (
    "https://terre-eygues.net/wp-json/wp/v2/pages"
    "?per_page=100&page=1&_fields=slug,link,content"
)
OUTPUT = Path(__file__).resolve().parent / "nyons_anecdotes.json"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class SummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.issue = ""
        self.rows: list[dict[str, str]] = []
        self._heading_tag = ""
        self._heading_parts: list[str] = []
        self._in_p = False
        self._in_strong = False
        self._in_em = False
        self._strong_parts: list[str] = []
        self._current_strong: list[str] = []
        self._em_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"h3", "h4", "h5"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "p":
            self._in_p = True
            self._strong_parts = []
            self._current_strong = []
            self._em_parts = []
        elif self._in_p and tag == "strong":
            self._in_strong = True
            self._current_strong = []
        elif self._in_p and tag == "em":
            self._in_em = True

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag:
            heading = clean("".join(self._heading_parts))
            if re.search(r"num[ée]ro\s+\d+", heading, re.I):
                self.issue = heading
            self._heading_tag = ""
        elif tag == "strong" and self._in_strong:
            text = clean("".join(self._current_strong))
            if text:
                self._strong_parts.append(text)
            self._in_strong = False
        elif tag == "em":
            self._in_em = False
        elif tag == "p" and self._in_p:
            if self._strong_parts:
                self.rows.append(
                    {
                        "title": self._strong_parts[-1],
                        "summary": clean("".join(self._em_parts)),
                        "issue": self.issue,
                    }
                )
            self._in_p = False
            self._in_strong = False
            self._in_em = False

    def handle_data(self, data: str) -> None:
        if self._heading_tag:
            self._heading_parts.append(data)
        if self._in_strong:
            self._current_strong.append(data)
        if self._in_em:
            self._em_parts.append(data)


SKIP = re.compile(
    r"^(?:sommaire|le mot|édito|edito|livres?(?:,| et|$)|revues?$|courrier|"
    r"cliquez|téléchargez|abonnement|le dossier$|rechercher|confidentialité|"
    r"assemblée générale|nos activités|in memoriam|un objet du musée$|"
    r"chroniques villageoises$|lecture d.un paysage$|patrimoine immatériel$|"
    r"pages provençales$|portrait$|hommage à|annonce de)",
    re.I,
)

LOCAL = re.compile(
    r"nyons|nyonsais|baronnies|eygues|pontias|randonne|arcades|saint-vincent|"
    r"champ de mars|oliv|scourtin|condorcet|venterol|mirabel|aubres|vinsobres|"
    r"sainte-jalle|les pilles|buis|rémuzat|taulignan|mollans|séderon|montbrun|"
    r"m[ée]vouillon|saint-may|rosans|la charce|vall[ée]e du lez",
    re.I,
)


# Ces formulations courtes sont des synthèses factuelles rédigées après lecture
# des articles PDF. La valeur associée indique la page physique du PDF.
PDF_FACTS: dict[str, tuple[str, int]] = {
    "Vallée de l’Ennuye en 1789": ("En juin 1788, le parlement du Dauphiné réclama à Louis XVI la réunion des États généraux, une décision qui toucha aussi les petites communautés de la vallée de l’Ennuye.", 5),
    "Scandale au couvent Saint-Césaire de Nyons": ("En 1767, trois bénédictines de Saint-Césaire refusèrent l’autorité de leur nouvelle prieure, jugée de naissance trop modeste ; leur fronde dura jusqu’en 1781.", 15),
    "Maréchaux-ferrants, famille Bise": ("Félix Bise reprit un atelier de maréchalerie à Nyons en 1926 ; quatre générations de la famille ont ensuite accompagné l’évolution de l’agriculture locale.", 23),
    "Présence espagnole dans le Nyonsais": ("La présence espagnole dans le Nyonsais s’est renforcée au fil des crises du XXe siècle, avant le jumelage de Nyons avec Nules au début des années 1990.", 27),
    "Site archéologique des Laurons et chapelle de Chausan": ("Aux Laurons, les fouilles ont révélé une villa gallo-romaine du IIIe siècle et des traces d’occupation encore plus anciennes sous les abords de la chapelle de Chausan.", 32),
    "Litiges autour des paluds de Mévouillon": ("Une charte de 1270 accordait aux habitants de Mévouillon un droit de pâturage dans les paluds de Gresse ; ce droit fut disputé pendant plus de six siècles.", 41),
    "Religion et administration au XVIIIe siècle": ("Dès 1740, le curé Jean-Charles Tardieu dressa à Nyons des tables récapitulatives des baptêmes, mariages et sépultures.", 45),
    "Les faux-timbres à Nyons en 1937": ("En 1937, un Nyonsais réglait ses achats avec de faux timbres de 50 centimes qu’il prétendait tenir de clients buralistes.", 48),
    "Jean Matuchet": ("Vicaire à Nyons en 1937 et sergent-chef aviateur, Jean Matuchet mourut le 5 août 1940 lorsque son Bréguet 693 fut abattu près d’Amiens.", 5),
    "Vallée de l’Ennuye": ("À la veille de la Révolution, les villages de la vallée de l’Ennuye réclamaient surtout de meilleurs chemins et le retour des foires pour faciliter leurs échanges.", 9),
    "Bâtiment de la Fraternité": ("Ancien hôpital de Nyons, le bâtiment de la Fraternité fut acheté en 1841 par la communauté méthodiste, rattachée à l’Église réformée en 1925.", 24),
    "Peintres régionaux": ("Les peintres des fresques locales ont longtemps travaillé sans signer ; les noms de Testard, Van Banken et Perrier n’apparaissent qu’au début du XVIIe siècle.", 28),
    "Serurier": ("Les archives municipales conservent un sauf-conduit délivré à Nyons le 12 août 1792 à Sérurier, futur maréchal d’Empire.", 37),
    "Obole au crabe": ("Une monnaie grecque du Ve siècle avant notre ère, ornée d’un crabe et découverte près de Nyons, témoigne d’échanges très anciens avec Marseille.", 40),
    "L’immigration à Nyons": ("Entre les deux guerres, des migrations autrefois saisonnières devinrent durables ; les immigrés représentaient alors environ 7 % de la population du canton de Nyons.", 5),
    "Jean-Baptiste de Planchette de Piégon": ("Né à Vaison en 1708, Jean-Baptiste de Planchette de Piégon exerça comme prêtre à Brette, petite communauté pourtant majoritairement protestante.", 11),
    "Histoire géologique de Nyons": ("Le territoire nyonsais fut autrefois recouvert par la mer voconcienne, bien avant le soulèvement qui donna naissance aux Alpes.", 17),
    "L’épidémie de choléra à Arpavon en 1884": ("En août 1884, une famille fuyant le choléra arriva à Arpavon avec un malade ; les observations de deux médecins aidèrent à comprendre sa transmission.", 24),
    "Aux origines de la chapelle Notre-Dame-du-bon-secours de Nyons (2e partie)": ("Notre-Dame-du-Bon-Secours fut officiellement inaugurée en 1864 ; sa cloche et les tableaux de Léon Alègre furent installés l’année suivante.", 38),
    "Bombardement de Suze-la-Rousse en 1944": ("Le 10 mai 1944, quinze bombes furent larguées au sud de Suze-la-Rousse, mais six seulement explosèrent ; l’origine du raid reste incertaine.", 43),
    "Des drayes aux chemins vicinaux (2e partie)": ("La loi de 1836 partagea l’entretien des chemins vicinaux entre communes et département ; Nyons en comptait près de quarante kilomètres.", 5),
    "Attaque de la diligence Nyons-Montélimar": ("Le 3 mars 1828, la diligence transportant l’argent de Nyons fut attaquée près de Venterol ; ni les coupables ni le butin ne furent retrouvés.", 11),
    "Notre-Dame-de-Beaulieu de Mirabel": ("À Mirabel, une pierre tombale de Notre-Dame-de-Beaulieu pourrait être celle de Dragonnet III de Montauban, inhumé en 1276.", 22),
    "La flore de Nyons": ("À Nyons, l’orientation des collines, le climat et la diversité des sols font se côtoyer des plantes méditerranéennes et montagnardes.", 29),
    "Couvent des Récollets de Nyons": ("Un couvent de Récollets occupa Nyons de 1660 à 1781 ; l’ancien bâtiment accueillit ensuite l’hôpital-hospice à partir de 1835.", 40),
    "Les lieux de sépulture à Nyons": ("Après l’interdiction des inhumations dans les églises et à l’intérieur des villes en 1776, Nyons dut créer des cimetières hors les murs.", 5),
    "Une monnaie de Constantin Ier": ("Une monnaie romaine du IVe siècle à l’effigie de Constantin Ier fut découverte en 1777 près de la chapelle de Chausan.", 16),
    "Les perles en verre du musée": ("Trois perles bleutées conservées au musée de Nyons ont été datées de l’âge du Bronze et attribuées à des ateliers d’Italie du Nord.", 18),
    "Georges Colomb": ("Georges Colomb passa ses dernières années, de 1940 à 1945, entre Buis-les-Baronnies et Nyons, où il écrivit sur Alésia et Vercingétorix.", 22),
    "Aux origines de Notre-Dame-du-Bon-Secours": ("La chapelle Notre-Dame-du-Bon-Secours concrétisa le vœu de l’abbé Francou, qui voulait remercier la Vierge après sa guérison.", 27),
    "Un marquis en rébellion": ("Un marquis des Baronnies libéra ses villageois de leurs servitudes tout en préparant des projets d’insurrection avec les émigrés avant de mourir près de Naples.", 33),
    "Emeute contre l’octroi": ("Les 5 et 6 juillet 1840, l’entrée en vigueur d’un nouveau mode de perception de l’octroi provoqua une émeute à Nyons.", 42),
    "Canal de la grande prairie": ("Dès le XVe siècle, le canal de la Grande Prairie faisait fonctionner des moulins et irriguait les jardins et les prés de Nyons.", 5),
    "Saint-May : restauration d’un patrimoine": ("L’église de Saint-May conserve un tableau de Louis Court représentant saint Sixte et saint Laurent, autrefois installé à l’abbaye de Bodon.", 16),
    "Famille Romieu-Desorgues": ("Installé à Nyons vers 1760, Antoine Alexandre Romieu-Desorgues devint en 1805 l’envoyé de Napoléon Ier auprès de la cour de Téhéran.", 17),
    "Nyons, station balnéaire et hivernale": ("À la fin du XIXe siècle, un ambitieux projet voulut transformer Nyons et les eaux de Condorcet en station thermale réputée.", 26),
    "Condorcet, hameau « la Bonté »": ("Né de parents inconnus en 1845, Gustave Auguste Celse connut le parcours des enfants abandonnés des hospices avant que son histoire ne soit retrouvée à Condorcet.", 31),
    "Quatre vallées et trois savants": ("Condorcet, Coriolis et Fresnel, trois grands savants français, possédaient tous des attaches familiales ou professionnelles dans les vallées de la région.", 37),
    "Accroissement des prénoms multiples": ("À Nyons, la multiplication des prénoms accompagna d’abord l’amélioration de l’administration des personnes et des biens.", 2),
    "Famille Romieu-Dessorgues (2e partie)": ("Après avoir été préfet, François Auguste Romieu-Dessorgues devint directeur des Beaux-Arts puis inspecteur général des Bibliothèques de l’Empire.", 5),
    "Une enfance à Nyons": ("En 1940, une famille mosellane quitta son village pour rester française et s’installa à Nyons, où plusieurs de ses membres demeurèrent après la guerre.", 17),
    "Famille Ailhaud (1e partie)": ("Au début du XVIIIe siècle, Jean Ailhaud commercialisa un prétendu remède universel ; sa diffusion lointaine enrichit durablement ses descendants.", 21),
    "Roger Pasturel": ("Roger Pasturel écrivit en 1984 une pastorale provençale mêlant traditions de la Nativité, crèches, Noëls et théâtre populaire.", 27),
    "Les drayes d’antan (1re partie)": ("En 1740, deux enquêteurs furent chargés de rétablir les drayes nyonsaises que certains propriétaires riverains avaient peu à peu absorbées.", 33),
    "Ecole ménagère ambulante": ("De 1921 à 1934, une école ménagère itinérante forma dans la Drôme les filles d’agriculteurs à la gestion du foyer et de l’exploitation.", 39),
    "Le scoutisme": ("Créé par Baden-Powell au début du XXe siècle, le scoutisme arriva dans le Nyonsais au cours des années 1930.", 45),
    "Les galériens protestants": ("Avant même 1685, des protestants du Nyonsais furent condamnés aux galères ; la revue retrace le sort de onze d’entre eux.", 5),
    "Rififi à la prison de Nyons": ("En août 1880, le gardien-chef de la prison de Nyons fut mis à la retraite après vingt-huit ans de service et un long conflit politico-religieux.", 18),
    "L’annonciation de Novezan": ("L’église de Novezan conserve l’une des cinq répliques françaises connues de la Santissima Annunziata de Florence ; son arrivée demeure mystérieuse.", 24),
    "Nyons, église Saint-Vincent": ("Sous l’église Saint-Vincent, les archéologues ont identifié un mur du VIe siècle, une tombe du Xe siècle et une borne milliaire romaine.", 9),
    "Pierre Louis Guilliny": ("Le soyeux Pierre-Louis Guilliny inventa un régulateur donnant une longueur constante aux flottes de soie, récompensé par une médaille d’or à Lyon.", 34),
    "F.V. Raspail : lettres de prison": ("Depuis sa prison, le savant et républicain François-Vincent Raspail se montrait déçu par 1848, mais gardait foi dans l’égalité entre les hommes.", 6),
    "Lissoirs carolingiens": ("Un galet de verre massif, probablement utilisé pour travailler le cuir ou le textile à l’époque carolingienne, a été retrouvé à Rousset-les-Vignes.", 42),
    "Tableaux de l’église Saint-Vincent (première partie)": ("Après la Révolution, plusieurs tableaux du couvent des Récollets furent transférés à Saint-Vincent, dont deux œuvres de Guy François.", 44),
    "Installation d’une confrérie de pénitents": ("En novembre 1789, vingt et un paroissiens des Pilles prirent l’habit des Pénitents blancs dans la chapelle Saint-Denis.", 5),
    "L’école supérieure de filles": ("Ouverte en 1882, l’école supérieure de filles de Nyons devint un cours complémentaire en 1932 puis un collège d’enseignement général en 1959.", 14),
    "Baron Tardieu de Saint-Aubanet": ("Né à Montaulieu en 1781, Jean Gabriel Tardieu servit sous plusieurs régimes avant de devenir baron en 1822 et maréchal de camp.", 26),
    "Tableaux de l’église Saint-Vincent": ("L’église Saint-Vincent conserve du mobilier doré et des tableaux du XVIIe siècle provenant des Récollets et des bénédictines de Saint-Césaire.", 30),
    "Jumelage Nyons-Mechernich": ("Le jumelage Nyons-Mechernich est né de l’attachement d’un professeur allemand à la vieille ville de Nyons et a surmonté les réticences de l’après-guerre.", 5),
    "L’école de Léoux": ("La petite école de Léoux, construite au prix d’importants efforts communaux après les lois scolaires de 1881-1882, ferma définitivement en 1962.", 15),
    "Histoire de l’eau à Nyons": ("En 1864, l’abbé Soulier estima que seule la source de la Sauve pouvait fournir assez d’eau aux fontaines et lavoirs de Nyons.", 5),
    "Fernand Rochas": ("Prisonnier cinq ans dans un stalag de Silésie, Fernand Rochas consigna ses poèmes dans un carnet noir en attendant son retour.", 37),
    "La Tour de Château Ratier": ("La tour de Château Ratier est le dernier vestige d’un château des Hospitaliers dominant Venterol, ruiné pendant les conflits du XVe siècle.", 43),
    "Jean-Charles Faure": ("Le colonel nyonsais Jean-Charles Faure fut grièvement touché à la main par un projectile lors de la bataille d’Eylau en 1807.", 5),
    "Saint Maurice sur Eygues": ("L’histoire du nom de Saint-Maurice-sur-Eygues conduit jusqu’aux affrontements entre Provençaux et Maures, fréquents du VIIIe au Xe siècle.", 15),
    "L’abbé Antoine Soulier": ("L’abbé Antoine Soulier fut à la fois prêtre, hydrologue, sourcier et géologue ; ses recherches visaient notamment à protéger les communes de la sécheresse.", 19),
    "La formation de la Lance": ("Le massif de la Lance est le résultat de transformations géologiques étalées sur des millions d’années.", 11),
    "Le pain à Nyons": ("À Nyons, le conseil de ville réglementait le pain pour prévenir à la fois les disettes et les fraudes des boulangers.", 6),
    "La Fontaine monumentale": ("Projetée en 1844, la fontaine du Champ-de-Mars ne fut achevée qu’en 1871 et souffrit longtemps d’un débit d’eau insuffisant.", 5),
    "Un document fondamental dans l’histoire de Nyons: Les lettres patentes du roi François 1er d’août 1641 y créant foires et marchés": ("Le marché du jeudi de Nyons rythme la vie de la ville depuis les lettres royales de 1541.", 13),
    "Quelques tableaux retrouvés provenant de l’église de Nyons": ("Une partie des tableaux classés de Saint-Vincent provient du couvent des Récollets et illustre la spiritualité franciscaine des XVIIe et XVIIIe siècles.", 21),
    "Intérêt de la céramique sigillée pour l’archéologie gallo-romaine": ("Le musée de Nyons expose des vases et tessons de céramique sigillée trouvés dans plusieurs villas gallo-romaines autour de l’ancienne Noïomagus.", 31),
    "Jeune instituteur du Nyonsais": ("En 1950, un jeune instituteur découvrit à Montaulieu une classe unique de neuf élèves dans un village de soixante-douze habitants sans électricité.", 41),
    "L’hôtel Colombet": ("L’hôtel Colombet s’établit au nord du Champ-de-Mars au début du XXe siècle, avant de passer des longues villégiatures aux séjours touristiques plus courts.", 5),
    "Querelles de clochers entre Novezan et Venterol": ("Novezan tenta autrefois de retrouver son indépendance face à Venterol ; leur union, née vers le XVe siècle, finit par devenir un mariage de raison.", 3),
    "Prisonnier de 1940 à 1945 – Témoignage de Julien BÉRARD": ("Captif de 1940 à 1945, Julien Bérard travailla dans une exploitation de huit cents hectares au sud de Berlin.", 23),
    "La place du Foussat": ("Avant de devenir la place Buffaven envahie d’automobiles, le Foussat servait de stationnement aux chevaux et de terrain de jeux aux enfants.", 29),
    "Le prieuré de saint Blaise à Montbrison-sur-Lez": ("Une chapelle édifiée vers 1150 donna naissance au prieuré Saint-Blaise, abandonné progressivement au XVIIIe siècle puis restauré en 2005.", 33),
    "Jour et Nuit au Musée": ("Lors de la Nuit des musées, le musée archéologique de Nyons consacra une exposition au fonctionnement des théâtres antiques de Narbonnaise.", 45),
    "Quelques habitants connus ou méconnus de la Place des Arcades": ("La place des Arcades a abrité des familles liées à Condorcet et à La Tour du Pin-La Charce, mais aussi des acteurs locaux aujourd’hui moins connus.", 5),
    "Mémoire de la Place des Arcades": ("Trois générations de libraires ont observé, depuis la même boutique des Arcades, plus d’un siècle de marchés, de jeux d’enfants et d’arrivée de l’automobile.", 12),
    "Un sentier de découverte à Condorcet": ("L’ancien village de Condorcet, mentionné dès le début du XIe siècle, a été dégagé de la végétation pour créer un sentier historique.", 23),
    "Les Fêtes internationales de l’Olivier ou Olivades 1964": ("Les premières Olivades de 1964 célébraient l’olivier nyonsais, que le gel dévastateur de 1956 avait failli faire disparaître.", 29),
    "Aspects récents de la population du Canton de Nyons": ("Les études démographiques du canton montrent un contraste persistant entre Nyons et les dix-sept autres communes rurales.", 39),
    "Un grand magasin nyonsais de naguère : Le Bazar": ("Pendant près d’un siècle, la famille Girard fit vivre à Nyons le Grand Bazar Universel, devenu ensuite Magasin Universel puis droguerie.", 5),
    "Rapport du pasteur Paul SEIGNOL sur l’activité au sein de la Résistance de M. le Docteur BOURDONGLE": ("Le docteur Bourdongle participa à l’organisation d’un réseau de Résistance dans le Nyonsais, activité relatée par le pasteur Paul Seignol.", 13),
    "Une relève dans le secteur du Mort-Homme en août 1918": ("En août 1918, le sergent Farnier consigna pendant une semaine sa relève au Mort-Homme afin de témoigner de la guerre vécue loin des journaux.", 17),
    "La représentation des plantes dans les collections et monuments locaux de l’Antiquité à la Renaissance": ("Dans les monuments anciens de la région, les plantes symbolisaient souvent une vertu, un vice, une fonction ou un personnage avant d’être représentées scientifiquement.", 25),
    "Des chantiers de la Jeunesse française à la Résistance": ("Créés après l’armistice de 1940 pour encadrer les jeunes démobilisés, les Chantiers de jeunesse fournirent ensuite des combattants à la Libération.", 33),
    "La séparation des Églises et de l’État": ("À Nyons, les relations entre catholiques et protestants restèrent plus calmes qu’au Parlement lors de la séparation des Églises et de l’État.", 51),
    "Nyons : 21 Janvier 1944, le drame de la déportation des Juifs Sarrois": ("Le 21 janvier 1944, une rafle à Nyons frappa des familles juives venues de Sarre dès 1935 et atteignit aussi la Résistance locale.", 5),
    "La libération de Nyons": ("Une Nyonsaise tint du 15 au 28 août 1944 un journal mêlant vie quotidienne, nouvelles militaires et réflexions politiques sur la Libération.", 13),
    "La fin de la guerre à Mirabel": ("À l’été 1944, Mirabel vit circuler voitures des maquisards, camions allemands et jeeps américaines, tandis que des parachutages alimentaient la Résistance.", 23),
    "La rue Henri Guironnet à Annonay": ("Henri Guironnet, dont une rue d’Annonay porte le nom, était un Ardéchois réfractaire au Service du travail obligatoire.", 25),
    "Balade floristique sur le Devès à Nyons": ("Le Devès abrite notamment l’aristoloche pistoloche, le brachypode rameux et l’anacamptis pyramidal, trois plantes étudiées par les botanistes locaux.", 27),
    "Les caisses d’Épargne en France et à Nyons": ("Les Caisses d’Épargne, nées en France en 1818, ont financé des œuvres sociales allant des bains-douches aux jardins ouvriers.", 47),
    "L’enseignement primaire à Nyons": ("Des photographies scolaires conservées à Nyons permettent de retrouver des générations d’élèves entre 1923 et 1966.", 5),
    "La caisse d’Épargne de Nyons – 1879-1987 : plus d’un siècle au service de l’économie locale": ("Créée sous régime municipal en 1879, la Caisse d’Épargne de Nyons devint autonome avant d’acquérir le statut de banque.", 39),
    "L’octroi en France et à Nyons": ("À Nyons, l’octroi taxait certaines marchandises à leur entrée dans la ville depuis le XIVe siècle ; il ne disparut qu’en 1942.", 5),
    "Voyage à travers le Nyonsais": ("Avant l’arrivée du chemin de fer, un voyage dans le Nyonsais mettait déjà en avant oliviers, truffes, vieille ville et vent du Pontias.", 17),
    "Un jour à Nyons (Le Pontias du 11 février 1866)": ("En février 1866, un visiteur décrivit dans Le Pontias les petites rues de Nyons et Notre-Dame-de-Bon-Secours.", 21),
    "Récente découverte archéologique à Sainte-Jalle": ("Des travaux près de Notre-Dame-de-Beauvert à Sainte-Jalle ont révélé sept stèles gallo-romaines datant probablement des IIe et IIIe siècles.", 23),
    "Les confitureries à Nyons": ("De l’après-1918 aux années 1970, deux confitureries nyonsaises employèrent jusqu’à deux cents personnes et produisirent jusqu’au quart des confitures françaises.", 35),
    "La Légion d’Honneur": ("Créée pour relier mérite ancien et moderne, la Légion d’honneur a changé d’effigie centrale au fil des régimes sans perdre son symbole.", 45),
    "Frédéric Autiéro : musicien": ("Frédéric Autiéro anima la vie musicale de Nyons à l’école de musique, à l’orgue et avec l’ensemble des Enfants du Pontias.", 5),
    "Et après Philis ? Quelques notes sur la famille de la Charce et ses biens": ("Les biens des derniers représentants régionaux de La Tour du Pin-La Charce furent progressivement dispersés à la fin du XVIIIe siècle.", 21),
    "Victor Cherbuliez (1829-1899)": ("Victor Cherbuliez, Genevois devenu Français et Nyonsais de cœur, entra à l’Académie française et publia une trentaine de romans.", 31),
    "« Nyons catholique », reflet d’un demi-siècle de vie religieuse dans notre ville": ("Le journal Nyons catholique accompagna la vie paroissiale de 1904 à 1956, de l’affaire Dreyfus à l’après-guerre.", 37),
    "Regard (critique) du curé sur les instituteurs de Venterol": ("Au XIXe siècle, le curé de Venterol adressa à son évêque des critiques acerbes contre les instituteurs du village.", 43),
    "Le Dr Henri Rochier – Distinction et dévouement": ("Maire de Nyons de 1912 à 1933, le docteur Henri Rochier modernisa l’eau, l’éclairage et la voirie de la ville.", 5),
    "A propos de l’inventaire après décès de la pharmacie de M. Marcel": ("Au XVIIe siècle, l’apprentissage chez un apothicaire, un cardeur ou un chapelier durait souvent à peine deux ans.", 13),
    "Le « Réveil » protestant en Drôme du Sud dans l’entre-deux-guerres": ("Dans l’entre-deux-guerres, des pasteurs du sud de la Drôme formèrent une brigade pour ranimer les paroisses et rouvrir des lieux de culte.", 17),
    "La vie dans les villages des Baronnies aux XIIe et XIIIe siècles": ("Aux XIIe et XIIIe siècles, la vie des villages des Baronnies s’organisait autour du château, du bourg et de son territoire.", 23),
    "Chasses anciennes interdites ou tolérées": ("En 1808 déjà, les gardes champêtres surveillaient dans la région des techniques de chasse aujourd’hui oubliées, comme la pipée ou les lèches à grives.", 29),
    "Découvertes archéologiques au giratoire des Laurons": ("La construction du giratoire des Laurons a mis au jour un habitat néolithique près d’un secteur déjà connu pour ses vestiges antiques.", 35),
    "Le Docteur Long, Maire et Conseiller général (1815-1896)": ("Le docteur Long, plusieurs fois maire de Nyons au XIXe siècle, améliora la salubrité et participa à la création de la bibliothèque municipale.", 5),
    "Le séjour à Nyons de F. Largo Caballero, ancien Président du Conseil espagnol": ("Assigné à résidence à Nyons en 1942, l’ancien chef du gouvernement espagnol Francisco Largo Caballero fut arrêté par la Gestapo en 1943.", 17),
    "La haute vallée du Lez et le massif de la Lance de la Préhistoire aux temps mérovingiens": ("Dans la haute vallée du Lez, les découvertes archéologiques attestent une présence humaine presque continue depuis environ cinquante mille ans.", 19),
    "La Poste dans la Drôme et à Nyons": ("Les premières marques postales datent de 1695 ; les archives montrent ensuite l’organisation progressive du service postal à Nyons.", 30),
    "Les « Cousins » provençaux des Pouilles": ("Deux villages des Pouilles parlent encore un franco-provençal hérité de soldats de Charles d’Anjou installés dans le sud de l’Italie au XIIIe siècle.", 43),
    "L’Elixir du Pontias et les Moulin, famille de liquoristes nyonsais": ("Commercialisé dès 1893 par la famille Moulin, l’Élixir du Pontias resta une spécialité nyonsaise jusqu’à l’essor des supermarchés dans les années 1960.", 47),
}


def fetch_pages() -> list[dict]:
    request = Request(API_URL, headers={"User-Agent": "agenda-nyons/1.0"})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def pdf_links_by_issue(pages: list[dict]) -> dict[str, str]:
    """Retrouve l'URL de chaque revue PDF à partir des pages annuelles."""
    result: dict[str, str] = {}
    for page in pages:
        rendered = page.get("content", {}).get("rendered", "")
        for raw_url in re.findall(r'href=["\']([^"\']+\.pdf)["\']', rendered, re.I):
            url = html.unescape(raw_url)
            filename = unquote(Path(urlsplit(url).path).name)
            issue_match = re.search(r"(?<!\d)([2-5]\d)(?!\d)", filename)
            if issue_match:
                # La dernière URL rencontrée remplace une éventuelle ancienne
                # copie devenue indisponible (cas du numéro 53).
                result[issue_match.group(1)] = url
    return result


def main() -> None:
    pages = fetch_pages()
    pdf_by_issue = pdf_links_by_issue(pages)
    candidates: list[dict[str, str | int]] = []
    seen_titles: set[str] = set()

    for page in pages:
        match = re.fullmatch(r"terre-d-?eygues-(19\d{2}|20\d{2})", page.get("slug", ""))
        if not match:
            continue

        year = match.group(1)
        parser = SummaryParser()
        parser.feed(page.get("content", {}).get("rendered", ""))

        for row in parser.rows:
            title = clean(row["title"]).strip(" .–—-")
            if title not in PDF_FACTS:
                continue
            normalized = re.sub(r"\W+", " ", title.lower()).strip()
            if normalized in seen_titles:
                continue

            seen_titles.add(normalized)
            issue_match = re.search(r"(\d+)", row.get("issue", ""))
            if not issue_match:
                raise ValueError(f"Numéro de revue introuvable pour {title}")
            issue = issue_match.group(1)
            pdf_url = pdf_by_issue.get(issue)
            if not pdf_url:
                raise ValueError(f"PDF du numéro {issue} introuvable pour {title}")
            fact, pdf_page = PDF_FACTS[title]
            candidates.append(
                {
                    "title": title,
                    "year": year,
                    "issue": issue,
                    "text": fact,
                    "pdf_page": pdf_page,
                    "source_url": f"{pdf_url}#page={pdf_page}",
                }
            )

    missing = set(PDF_FACTS) - {str(item["title"]) for item in candidates}
    if missing:
        raise ValueError(f"Articles PDF non retrouvés : {sorted(missing)}")

    candidates.sort(key=lambda item: (-int(item["year"]), int(item["issue"]), int(item["pdf_page"])))
    entries: list[dict[str, str]] = []
    for candidate in candidates:
        title = str(candidate["title"])
        year = str(candidate["year"])
        issue = str(candidate["issue"])
        pdf_page = str(candidate["pdf_page"])
        entries.append(
            {
                "id": hashlib.sha256(f"{issue}|{title}|{candidate['text']}".encode("utf-8")).hexdigest()[:16],
                "text": str(candidate["text"]),
                "article_title": title,
                "publication_year": year,
                "issue": issue,
                "pdf_page": pdf_page,
                "source_label": f"Terre d’Eygues n°{issue}, PDF p. {pdf_page} — {title}",
                "source_url": str(candidate["source_url"]),
            }
        )

    payload = {
        "source": "Terre d’Eygues — Histoire et Patrimoine du Nyonsais et des Baronnies",
        "source_index": "https://terre-eygues.net/revue/achat-et-telechargement/",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(entries)} anecdotes vérifiées dans les PDF et enregistrées dans {OUTPUT.name}")


if __name__ == "__main__":
    main()
