"""Present official event details without a paid generation service."""
import re


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clean_source_text(value):
    """Cut recommendations, pagination and municipal footer, even on short pages."""
    value = clean(value)
    value = re.split(
        r"ces [ée]v[ée]nements pourraient vous int[ée]resser|"
        r"abonnement aux informations|recevez les derni[èe]res actualit[ée]s|"
        r"mentions l[ée]gales|politique de confidentialit[ée]",
        value, maxsplit=1, flags=re.I,
    )[0]
    # Pagination following the last event in a listing (including a truncated cache).
    value = re.sub(r"\s+(?:\d+\s+){2,}(?:[.…]+\s*)?(?:\d+\s*)*(?:->|→)?\s*$", "", value)
    return value.strip()


def event_description(event, detail_text, practical):
    text = clean_source_text(detail_text)
    # The municipal detail page has a Retour link immediately before its content.
    if re.search(r"(?:^|\s)Retour\s", text):
        text = re.split(r"(?:^|\s)Retour\s+", text, maxsplit=1)[1]
    elif event.get("title") and text.startswith(event["title"]):
        # Without an identified content boundary, prefer the known list summary.
        text = ""
    for key in ("date_time", "location_name", "address", "email", "phone", "website"):
        marker = clean(practical.get(key, ""))
        if marker:
            position = text.casefold().find(marker.casefold())
            if position >= 0:
                text = text[:position]
    text = re.sub(r"\bDescription\s+", "", text).strip()
    return text or clean_source_text(event.get("summary", ""))


def practical_text(practical, when):
    place = ", ".join(filter(None, [
        clean(practical.get("location_name", "")).rstrip(" ,"),
        clean(practical.get("address", "")),
    ]))
    text = clean(practical.get("date_time", "")) or when
    if place:
        text += f", {place}"
    text = text.rstrip(" .") + "."
    contacts = []
    phone = clean(practical.get("phone", ""))
    if re.fullmatch(r"0\d{9}", phone):
        phone = " ".join(phone[i:i + 2] for i in range(0, 10, 2))
    if phone:
        contacts.append(phone)
    if practical.get("email"):
        contacts.append(clean(practical["email"]))
    if contacts:
        text += " Renseignements : " + " ou ".join(contacts) + "."
    return text


def local_editorial(event, detail_text, practical, when):
    title = clean(event["title"])
    summary = clean_source_text(event.get("summary", ""))
    description = event_description(event, detail_text, practical)
    subject = title.casefold()
    period = when if when.startswith("du ") else f"le {when}"
    context = description + " " + summary
    if ("clémentine" in subject and re.search(r"\bnul[èe]s\b", context, re.I)
            and "olive piqu" in context.casefold()
            and re.search(r"amiti[ée].*nyons.nul", context, re.I)):
        intro = "À l’occasion de la Fête de l’Olive piquée, l’association « Amitié Nyons-Nulès » propose une vente de clémentines bio à Nyons. Les fruits annoncés proviennent de la région de Nulès."
        description = description.rstrip(" .") + ". " + practical_text(practical, when).split(" Renseignements :", 1)[0]
        why = "Ce rendez-vous associe les fruits de la région de Nulès à la vie associative nyonsaise. Si vous êtes venu pour la Fête de l’Olive piquée, vous pouvez aussi repérer le stand tenu par l’association « Amitié Nyons-Nulès »."
        question = "Connaissiez-vous déjà les clémentines de la région de Nulès ?"
        # The programme already supplies the introduction; do not repeat the listing.
        summary = ""
    elif "culinaire" in subject or "cuisine" in subject:
        intro = f"À Nyons, l’{title[0].lower() + title[1:]} est proposé {period}."
        why = "Cet atelier permet de passer à la préparation : les recettes et les gestes annoncés sont détaillés dans le programme. Pensez à la boîte hermétique si l’organisation vous demande d’en apporter une pour emporter vos réalisations."
        if "accompagnement" in subject:
            why = "L’intérêt de cet atelier est de préparer soi-même les accompagnements, au lieu de se limiter à choisir le plat principal. Regardez les recettes au programme pour choisir ce que vous aimeriez apprendre à refaire chez vous."
        question = "Quel accompagnement aimeriez-vous préparer vous-même pour les fêtes ?" if "fête" in subject else "Quelle préparation aimeriez-vous apprendre à refaire chez vous ?"
    elif "concert" in subject:
        intro = f"À Nyons, le {title[0].lower() + title[1:]} a lieu {period}."
        why = "Assister à ce concert, c’est prendre le temps d’écouter les musiciens en direct. Gardez les horaires et l’adresse sous la main pour rejoindre le lieu du concert avant le début."
        if "élèves" in description or "élève" in description:
            why = "Ce rendez-vous permet d’écouter les élèves et de découvrir le travail mené depuis la rentrée. Une autre manière de connaître l’école de musique, à travers ceux qui y apprennent et ceux qui les accompagnent."
        question = "Avez-vous déjà assisté à un concert de cette école de musique ?" if "école" in subject else "Qu’aimeriez-vous retrouver dans ce concert ?"
    elif "conférence" in subject:
        intro = f"À Nyons, {title} est au programme {period}."
        why = "Le sujet de cette conférence vous intéresse ? Le programme ci-dessus permet de préparer votre écoute et de noter les questions que vous aimeriez approfondir."
        question = "Quelle question aimeriez-vous approfondir pendant cette conférence ?"
    else:
        intro = f"À Nyons, {title} est au programme {period}."
        why, question = subject_copy(subject, description)
    if summary:
        intro += " " + summary
    return {
        "seo_title": title if "nyons" in subject else f"{title} à Nyons",
        "meta_description": f"{title} : {clean(practical.get('date_time')) or when}. {clean(practical.get('location_name')) or clean(practical.get('address'))}",
        "intro": intro,
        "story": description or summary or title,
        "why_it_matters": why,
        "practical": practical_text(practical, when),
        "reader_question": question,
        "_fallback": True,
    }


def subject_copy(subject, description):
    """Keep the invitation relevant to the actual event, without inventing its programme."""
    if "heures douces" in subject:
        return ("Les créations originales des Pépites du 31 se découvrent sur plusieurs semaines. Le vernissage est un rendez-vous distinct des jours habituels d’ouverture : choisissez votre passage selon que vous souhaitez rencontrer les artistes ou parcourir l’exposition.", "Quelle création vous donne envie de pousser la porte d’une galerie : peinture, objet ou pièce d’artisanat ?")
    if "libre d’être" in subject or "libre d'être" in subject:
        return ("Cette exposition associe la découverte d’œuvres au soutien du Planning Familial. Le programme précise la part des ventes reversée à l’association et le rendez-vous du vernissage.", "Quelle place accordez-vous aux expositions qui soutiennent une association locale ?")
    if "exposition" in subject:
        return ("Une exposition se découvre aussi en prenant son temps devant quelques œuvres. Repérez les jours d’ouverture et les éventuelles rencontres avec les artistes dans le programme.", "Quel détail vous retient devant une œuvre : sa couleur, sa matière ou le sujet représenté ?")
    if "après-midi de noël" in subject:
        return ("Les animations se succèdent au fil de l’après-midi : jeux et ateliers, passage du Père Noël puis goûter. Arrivez en fonction de ce que les enfants souhaitent retrouver, et pensez au pull de Noël demandé dans l’annonce.", "Les enfants préfèrent-ils les jeux en bois, l’atelier de Noël ou le passage du Père Noël ?")
    if "illumination" in subject:
        return ("Le lancement des lumières se prolonge par une déambulation en musique. La Ville propose de préparer sa propre lanterne en papier : un petit projet à faire avant de rejoindre le cortège.", "Avez-vous déjà fabriqué une lanterne pour accompagner les illuminations de Noël ?")
    if "arcades" in subject:
        return ("Cette journée réunit livres, dégustations et démonstration d’artisanat autour de la librairie Pinet. De quoi faire plusieurs découvertes au même endroit, sous les arcades.", "Sous les arcades, vous vous arrêteriez d’abord pour un livre ou une démonstration d’artisanat ?")
    if "apéro book" in subject or "apero book" in subject:
        if "fajnzylberg" in subject:
            return ("La rencontre porte sur la transmission d’un témoignage familial écrit après la déportation. Roger Fajnzylberg explique le parcours des carnets de son père et leur publication : prenez le temps de lire la présentation avant l’échange.", "Comment transmettez-vous les récits et les documents conservés dans votre famille ?")
        return ("Rencontrer une romancière permet de parler des personnages, des lieux et du travail d’écriture. Les ouvrages présentés dans l’annonce donnent un point de départ à la discussion.", "Quel lieu ou quel personnage d’un roman vous reste longtemps en mémoire ?")
    if "conseil municipal" in subject:
        return ("La séance est annoncée ouverte à tous. Assister aux délibérations permet de suivre directement les affaires de la commune ; ce rendez-vous se distingue d’une permanence ou d’un entretien individuel.", "Avez-vous déjà assisté à une séance du conseil municipal de Nyons ?")
    if "constellations familiales" in subject:
        return ("L’annonce présente une séance animée par Asma au collectif Le Papillon. Pour connaître le déroulement, la participation demandée et les modalités d’accueil, contactez directement l’organisatrice au numéro indiqué.", "Quels renseignements souhaitez-vous obtenir auprès de l’organisatrice avant de vous inscrire ?")
    if "réveillon" in subject:
        return ("Le repas et le bal sont réunis dans une même soirée. Avant de réserver auprès du Comité des Fêtes, vérifiez le nombre de places souhaitées et les modalités communiquées par l’organisation.", "Pour le réveillon, vous aimez surtout le repas partagé ou le moment de rejoindre la piste de danse ?")
    if "calèche" in subject:
        return ("La calèche propose une autre façon de profiter du centre-ville pendant les fêtes. Le point de départ précis et les modalités de passage sont à demander à l’Union des Entreprises du Nyonsais.", "Avec qui aimeriez-vous faire une promenade en calèche dans Nyons ?")
    if "olive piquée" in subject:
        return ("La fête permet de découvrir plusieurs étapes, de la cueillette à la dégustation. Certaines animations ont leur propre horaire : repérez celles que vous souhaitez suivre avant de choisir votre arrivée.", "Avez-vous déjà préparé vos propres olives piquées pour les fêtes ?")
    if "tombola" in subject:
        return ("La vente des billets s’étend sur plusieurs jours, tandis que le tirage a son propre horaire. Gardez votre billet et repérez le rendez-vous annoncé pour connaître les résultats.", "Avez-vous l’habitude de participer aux tombolas des associations nyonsaises ?")
    if "bridge" in subject:
        return ("Le tournoi réunit les joueurs autour des cartes pour soutenir le Téléthon. Contactez le club pour les modalités de participation et l’organisation des tables.", "Vous jouez au bridge depuis longtemps ou vous aimeriez découvrir ce jeu ?")
    if "padel" in subject:
        return ("Le Tennis Club consacre une journée au padel pour le Téléthon. Renseignez-vous auprès du club sur les créneaux et les modalités de participation avant de rejoindre les courts.", "Avez-vous déjà essayé le padel sur les courts de Nyons ?")
    if "basket" in subject:
        return ("Ce tournoi annonce une formule 3×3 ouverte à tous. Le Basket Club précise la participation minimale et le soutien au Téléthon : contactez-le pour composer ou inscrire votre équipe.", "Avec qui formeriez-vous votre équipe pour un tournoi de basket 3×3 ?")
    if "pétanque" in subject:
        return ("Le concours est annoncé en triplette montée et ouvert aux licenciés comme aux non-licenciés. Pensez à constituer votre équipe et à demander les conditions d’inscription à Nyons Pétanque.", "À la pétanque, vous préférez pointer ou tirer ?")
    if "bpco" in subject:
        return ("Ce rendez-vous d’information se tient pendant le marché hebdomadaire. Les professionnels de l’Orsac-Atrir annoncés sur place peuvent expliquer le déroulement des ateliers et du dépistage proposé.", "Quelles informations souhaiteriez-vous demander aux professionnels présents sur le stand ?")
    if "téléthon" in subject:
        if "parcours" in subject:
            return ("Les stands alimentaires et le parcours parents-enfants ont des horaires distincts. Repérez le créneau du parcours si vous venez en famille, puis prenez le temps de découvrir les stands solidaires.", "Vous viendriez plutôt pour le parcours en famille ou pour retrouver les stands solidaires ?")
        if "musicale" in subject:
            return ("Une animation musicale accompagne cette soirée de soutien au Téléthon. Le lieu annoncé permet de rejoindre le rendez-vous dans le centre de Nyons.", "Quel souvenir gardez-vous des animations musicales organisées pour le Téléthon à Nyons ?")
        return ("Ce rendez-vous permet de soutenir le Téléthon en retrouvant les bénévoles de Nyons. L’annonce détaille la vente ou l’animation proposée et les conditions de participation.", "Quelle animation solidaire aimez-vous retrouver pendant le Téléthon à Nyons ?")
    if "marché" in subject or "noël" in subject:
        return ("Ces rendez-vous de fin d’année permettent de découvrir les propositions des exposants et des organisateurs locaux. Le programme distingue les animations, les stands et leurs horaires : gardez ces repères pour organiser votre passage.", "Pour les fêtes, cherchez-vous plutôt un cadeau d’artisan ou une spécialité gourmande ?")
    return ("Le programme de ce rendez-vous est présenté ci-dessus avec ses informations concrètes. Pour une précision sur l’accueil ou les conditions de participation, utilisez le contact de l’organisation lorsqu’il est indiqué.", "Avez-vous déjà participé à ce rendez-vous à Nyons ?")
